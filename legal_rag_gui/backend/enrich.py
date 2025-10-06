"""High level enrichment helpers (summary, keywords, tooltips)."""
from __future__ import annotations

import re
from typing import Dict, Iterable, List

from .ai_client import OpenAIManager


def extract_keywords(text: str, *, topk: int = 5) -> List[str]:
    tokens = re.findall(r"[А-Яа-яA-Za-z]{4,}", text.lower())
    stop = {
        "российской",
        "федерации",
        "настоящего",
        "кодекса",
        "статья",
        "глава",
    }
    freq: Dict[str, int] = {}
    for token in tokens:
        if token in stop:
            continue
        freq[token] = freq.get(token, 0) + 1
    return [word for word, _ in sorted(freq.items(), key=lambda item: item[1], reverse=True)[:topk]]


def make_summary(manager: OpenAIManager, text: str) -> str:
    summary = manager.summarize(text)
    return summary or text[:160]


def enrich_articles(manager: OpenAIManager, texts: Iterable[str]) -> List[dict]:
    results = []
    for text in texts:
        summary = make_summary(manager, text)
        keywords = extract_keywords(text)
        results.append({"summary": summary, "keywords": keywords})
    return results


__all__ = ["extract_keywords", "make_summary", "enrich_articles"]
