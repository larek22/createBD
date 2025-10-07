from __future__ import annotations

import logging
import math
import re
from typing import List

from .store import ArticleRecord, Store

LOGGER = logging.getLogger("legal_rag_search")


def _score(query_tokens: List[str], record: ArticleRecord) -> float:
    if not query_tokens:
        return 0.0
    overlap = len(set(query_tokens) & set(record.tokens))
    text = record.text.lower()
    bonus = 0.0
    for token in query_tokens:
        if token in text:
            bonus += 0.2
    return overlap + bonus


def search(store: Store, query: str, limit: int = 5) -> List[dict]:
    LOGGER.info("Searching for: %s", query)
    tokens = [tok.lower() for tok in re.findall(r"[А-Яа-яA-Za-z]{3,}", query)]
    scored = []
    for record in store.list_records():
        score = _score(tokens, record)
        if score > 0:
            scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    results = []
    for score, record in scored[:limit]:
        results.append(
            {
                "id": record.id,
                "code": record.code,
                "title": record.title,
                "article": record.article,
                "chapter": record.chapter,
                "part": record.part,
                "summary": record.summary,
                "source": record.source,
                "score": round(score, 3),
            }
        )
    return results


__all__ = ["search"]
