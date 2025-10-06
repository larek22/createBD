"""Simple legal-aware chunking utilities."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Sequence

from .parser_rtf import extract_text

ARTICLE_PATTERN = re.compile(r"(?mi)^\s*статья\s+(\d+(?:\.\d+)*)\s*(.*)$")
CHAPTER_PATTERN = re.compile(r"(?mi)^\s*глава\s+(\d+(?:\.\d+)*)\s*(.*)$")


@dataclass
class Article:
    identifier: str
    heading: str
    body: str
    chapter: str | None = None

    def to_payload(self, *, code: str, title: str, source: Path) -> dict:
        return {
            "code": code,
            "title": title,
            "article": self.identifier,
            "chapter": self.chapter,
            "text": self.body,
            "heading": self.heading,
            "source": str(source),
            "created_at": datetime.utcnow().isoformat() + "Z",
        }


class Chunker:
    """Extract articles and chapters from a plain text document."""

    def __init__(self, auto_articles: bool = True) -> None:
        self.auto_articles = auto_articles

    def parse_file(self, path: Path) -> List[Article]:
        text = extract_text(path)
        return self.parse_text(text)

    # ------------------------------------------------------------------
    def parse_text(self, text: str) -> List[Article]:
        cleaned = self._normalize(text)
        if not self.auto_articles:
            return [Article(identifier="custom", heading="Полный текст", body=cleaned)]

        chapters = list(CHAPTER_PATTERN.finditer(cleaned))
        articles = list(ARTICLE_PATTERN.finditer(cleaned))
        if not articles:
            return [Article(identifier="full", heading="Текст документа", body=cleaned)]

        chapter_for_pos = self._build_chapter_index(chapters)
        results: List[Article] = []
        for idx, match in enumerate(articles):
            start = match.end()
            end = articles[idx + 1].start() if idx + 1 < len(articles) else len(cleaned)
            body = cleaned[start:end].strip()
            identifier = match.group(1)
            heading = match.group(0).strip()
            chapter = chapter_for_pos(match.start())
            if body:
                results.append(Article(identifier=identifier, heading=heading, body=body, chapter=chapter))
        return results

    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(text: str) -> str:
        text = text.replace("\r", "\n")
        text = re.sub(r"\u00A0", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _build_chapter_index(matches: Sequence[re.Match[str]]):
        positions = [(m.start(), m.group(1)) for m in matches]

        def lookup(pos: int) -> str | None:
            target = None
            for start, ident in positions:
                if start <= pos:
                    target = ident
                else:
                    break
            return target

        return lookup


def chunk_files(paths: Iterable[Path], *, auto_articles: bool = True) -> List[Article]:
    chunker = Chunker(auto_articles=auto_articles)
    all_articles: List[Article] = []
    for path in paths:
        all_articles.extend(chunker.parse_file(path))
    return all_articles


__all__ = ["Article", "Chunker", "chunk_files"]
