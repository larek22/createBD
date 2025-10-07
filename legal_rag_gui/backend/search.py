"""Search helpers for the FastAPI layer."""
from __future__ import annotations

import json
import logging
from typing import Dict, List

from pydantic import BaseModel

from ..db.qdrant_client import QdrantManager
from ..utils.config import SettingsStore
from .ai_client import get_client

LOGGER = logging.getLogger(__name__)


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5
    mode: str = "semantic"


class SearchResponse(BaseModel):
    items: List[dict]


class SearchService:
    def __init__(self, settings: SettingsStore | None = None) -> None:
        self.settings = settings or SettingsStore()

    # ------------------------------------------------------------------
    def search(self, request: SearchRequest) -> SearchResponse:
        query = request.query.strip()
        if not query:
            return SearchResponse(items=[])

        client = get_client(self.settings.data.openai_api_key)
        qdrant = QdrantManager(self.settings.data.qdrant_url, self.settings.data.qdrant_api_key or None)
        LOGGER.info("Search query: %s", query)

        title_vec = client.embed([query])[0]
        body_vec = client.embed([query])[0]

        title_points = qdrant.search(title_vec, vector_name="title_vec", limit=max(20, request.top_k * 4))
        body_points = qdrant.search(body_vec, vector_name="body_vec", limit=max(40, request.top_k * 6))

        combined = self._combine_rrf(title_points, body_points)
        top_candidates = combined[: max(12, request.top_k * 2)]
        reranked = self._rerank(client, query, top_candidates)
        final = reranked[: request.top_k]
        return SearchResponse(items=final)

    # ------------------------------------------------------------------
    @staticmethod
    def _combine_rrf(title_points, body_points, k: int = 60, w_title: float = 0.6, w_body: float = 0.4) -> List[dict]:
        scores: Dict[str, float] = {}
        payloads: Dict[str, dict] = {}

        for rank, point in enumerate(title_points, start=1):
            pid = str(point.id)
            payloads[pid] = dict(point.payload or {})
            scores[pid] = scores.get(pid, 0.0) + w_title / (k + rank)

        for rank, point in enumerate(body_points, start=1):
            pid = str(point.id)
            payloads.setdefault(pid, dict(point.payload or {}))
            scores[pid] = scores.get(pid, 0.0) + w_body / (k + rank)

        ranked = [
            {**payloads[pid], "score": score}
            for pid, score in sorted(scores.items(), key=lambda item: item[1], reverse=True)
        ]
        return ranked

    # ------------------------------------------------------------------
    def _rerank(self, client, query: str, candidates: List[dict]) -> List[dict]:
        if not candidates or not self.settings.data.openai_api_key:
            return candidates

        payload = {
            "query": query,
            "candidates": [
                {
                    "index": idx,
                    "article": item.get("article", ""),
                    "summary": item.get("summary", ""),
                    "text": (item.get("text") or "")[:1200],
                }
                for idx, item in enumerate(candidates, start=1)
            ],
        }

        try:
            response = client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Ты юридический эксперт. Оцени отрывки к запросу. Верни JSON вида "
                            "{\"scores\":[{\"index\":1,\"score\":87}]}"
                        ),
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                model="gpt-4.1-mini",
            )
            data = json.loads(response)
            order: Dict[int, float] = {
                int(entry.get("index", 0)): float(entry.get("score", 0.0))
                for entry in data.get("scores", [])
                if int(entry.get("index", 0)) > 0
            }
            scored = []
            for idx, item in enumerate(candidates, start=1):
                extra = order.get(idx)
                if extra is not None:
                    item = dict(item)
                    item["score"] = extra
                scored.append(item)
            scored.sort(key=lambda item: item.get("score", 0.0), reverse=True)
            return scored
        except Exception as exc:  # pragma: no cover - network or parsing issues
            LOGGER.warning("GPT rerank fallback: %s", exc)
            return candidates


__all__ = ["SearchService", "SearchRequest", "SearchResponse"]
