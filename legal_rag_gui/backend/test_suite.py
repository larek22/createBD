from __future__ import annotations

from typing import Dict

from .store import Store


def run_quality_checks(store: Store) -> Dict[str, object]:
    records = store.list_records()
    article_count = len(records)
    chapters = sorted({rec.chapter for rec in records if rec.chapter})
    parts = sorted({rec.part for rec in records if rec.part})
    return {
        "articles_indexed": article_count,
        "chapters_present": chapters,
        "parts_present": parts,
        "status": "ok" if article_count else "empty",
    }


__all__ = ["run_quality_checks"]
