from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import List, Optional

from .store import Store, create_record

LOGGER = logging.getLogger("legal_rag_ingest")

ARTICLE_RE = re.compile(r"(?mi)^\s*Статья\s+(\d+[\.\d]*)")
CHAPTER_RE = re.compile(r"(?mi)^\s*Глава\s+(\d+[\.\d]*)")


def read_text(path: Path) -> str:
    if path.suffix.lower() == ".txt":
        return path.read_text("utf-8")
    if path.suffix.lower() == ".rtf":
        # crude RTF cleaner
        data = path.read_text("utf-8", errors="ignore")
        data = re.sub(r"\\'[0-9a-fA-F]{2}", "", data)
        data = data.replace("\\par", "\n")
        data = re.sub(r"\\[a-zA-Z]+-?\d* ?", "", data)
        data = data.replace("{", "").replace("}", "")
        return data
    raise ValueError(f"Unsupported file type: {path.suffix}")


def extract_articles(text: str) -> List[dict]:
    items: List[dict] = []
    chapters = list(CHAPTER_RE.finditer(text))
    current_chapter: Optional[str] = None
    chapter_positions = {m.start(): m.group(1) for m in chapters}

    article_matches = list(ARTICLE_RE.finditer(text))
    for idx, match in enumerate(article_matches):
        start = match.end()
        end = article_matches[idx + 1].start() if idx + 1 < len(article_matches) else len(text)
        article_body = text[start:end].strip()
        article_name = match.group(1).rstrip('.')
        # determine chapter by the closest preceding chapter marker
        preceding_positions = [pos for pos in chapter_positions if pos <= match.start()]
        if preceding_positions:
            nearest = max(preceding_positions)
            current_chapter = chapter_positions[nearest]
        snippet = article_body.split("\n", 1)[0][:200]
        tokens = sorted({tok.lower() for tok in re.findall(r"[А-Яа-яA-Za-z]{3,}", article_body)})
        items.append(
            {
                "article": article_name,
                "chapter": current_chapter,
                "text": article_body,
                "summary": snippet,
                "tokens": tokens,
            }
        )
    if not items:
        cleaned = text.strip()
        snippet = cleaned.split("\n", 1)[0][:200]
        tokens = sorted({tok.lower() for tok in re.findall(r"[А-Яа-яA-Za-z]{3,}", cleaned)})
        items.append({
            "article": "—",
            "chapter": None,
            "text": cleaned,
            "summary": snippet,
            "tokens": tokens,
        })
    return items


def ingest_file(store: Store, *, path: Path, code: str, title: str, part: Optional[str]) -> dict:
    LOGGER.info("Reading document: %s", path)
    text = read_text(path)
    articles = extract_articles(text)
    records = []
    for item in articles:
        record = create_record(
            code=code,
            title=title,
            article=item["article"],
            chapter=item.get("chapter"),
            part=part,
            text=item["text"],
            summary=item["summary"],
            source=str(path),
            tokens=item["tokens"],
        )
        records.append(record)
    stats = store.add_records(records)
    LOGGER.info("Ingest finished: %s", stats)
    return {"articles": len(articles), **stats}


__all__ = ["ingest_file"]
