"""Search helpers for the FastAPI layer."""
from __future__ import annotations

import logging
from typing import List

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

    def search(self, request: SearchRequest) -> SearchResponse:
        client = get_client(self.settings.data.openai_api_key)
        qdrant = QdrantManager(self.settings.data.qdrant_url, self.settings.data.qdrant_api_key or None)
        LOGGER.info("Search query: %s", request.query)
        vec = client.embed([request.query])[0] if request.mode == "semantic" else client.embed([request.query])[0]
        points = qdrant.search(vec, limit=request.top_k)
        items = []
        for point in points:
            payload = point.payload or {}
            payload.update({"score": point.score})
            items.append(payload)
        return SearchResponse(items=items)


__all__ = ["SearchService", "SearchRequest", "SearchResponse"]
