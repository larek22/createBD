from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional

LOGGER = logging.getLogger("legal_rag_store")


@dataclass
class ArticleRecord:
    """Represents a single legal article entry stored in the index."""

    id: str
    code: str
    title: str
    article: str
    chapter: Optional[str]
    part: Optional[str]
    text: str
    summary: str
    source: str
    tokens: List[str]


class Store:
    """Thread-safe JSON backed storage for indexed legal articles."""

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path
        self._base_path.mkdir(parents=True, exist_ok=True)
        self._index_path = self._base_path / "index.json"
        self._lock = threading.Lock()
        self._records: Dict[str, ArticleRecord] = {}
        self._load()

    # ------------------------------------------------------------------
    def _load(self) -> None:
        if not self._index_path.exists():
            LOGGER.info("Storage file %s does not exist yet", self._index_path)
            return
        try:
            data = json.loads(self._index_path.read_text("utf-8"))
        except json.JSONDecodeError as exc:
            LOGGER.error("Failed to load storage JSON: %s", exc)
            return
        for item in data:
            try:
                record = ArticleRecord(**item)
                self._records[record.id] = record
            except TypeError as exc:
                LOGGER.warning("Skipping malformed record: %s", exc)

    # ------------------------------------------------------------------
    def _flush(self) -> None:
        with self._index_path.open("w", encoding="utf-8") as handle:
            json.dump([asdict(rec) for rec in self._records.values()], handle, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    def add_records(self, records: List[ArticleRecord]) -> Dict[str, int]:
        """Insert or update records and return stats about the operation."""

        added = 0
        updated = 0
        with self._lock:
            for record in records:
                if record.id in self._records:
                    self._records[record.id] = record
                    updated += 1
                else:
                    self._records[record.id] = record
                    added += 1
            self._flush()
        return {"added": added, "updated": updated, "total": len(self._records)}

    # ------------------------------------------------------------------
    def list_records(self) -> List[ArticleRecord]:
        with self._lock:
            return list(self._records.values())

    # ------------------------------------------------------------------
    def clear(self) -> None:
        with self._lock:
            self._records.clear()
            if self._index_path.exists():
                os.remove(self._index_path)


def create_record(
    *,
    code: str,
    title: str,
    article: str,
    chapter: Optional[str],
    part: Optional[str],
    text: str,
    summary: str,
    source: str,
    tokens: List[str],
) -> ArticleRecord:
    record_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{code}|{article}|{source}"))
    return ArticleRecord(
        id=record_id,
        code=code,
        title=title,
        article=article,
        chapter=chapter,
        part=part,
        text=text,
        summary=summary,
        source=source,
        tokens=tokens,
    )


__all__ = ["Store", "ArticleRecord", "create_record"]
