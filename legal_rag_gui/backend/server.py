"""FastAPI application used by the PySide6 GUI."""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from qdrant_client import QdrantClient

from ..utils.config import SettingsStore
from ..utils.logger import configure_logging
from .ai_client import get_client
from .ingest import IngestRequest, IngestService
from .search import SearchRequest, SearchResponse, SearchService
from .test_suite import QualityReport, TestRequest, TestService


class Settings(BaseModel):
    qdrant_url: str
    qdrant_api_key: str | None = None
    openai_api_key: str | None = None
    port: int = 8765


configure_logging()
LOGGER = logging.getLogger(__name__)

_store = SettingsStore()
settings = Settings(
    qdrant_url=os.getenv("QDRANT_URL", _store.data.qdrant_url),
    qdrant_api_key=os.getenv("QDRANT_API_KEY", _store.data.qdrant_api_key or None),
    openai_api_key=os.getenv("OPENAI_API_KEY", _store.data.openai_api_key or None),
    port=int(os.getenv("APP_PORT", str(_store.data.last_backend_port))),
)

app = FastAPI(title="Legal RAG Studio Backend", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

qdrant = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

_ingest = IngestService(_store)
_search = SearchService(_store)
_tests = TestService(_store)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "qdrant_url": settings.qdrant_url}


@app.get("/health/qdrant")
def health_qdrant() -> dict:
    try:
        collections = qdrant.get_collections()
        return {"ok": True, "collections": [c.name for c in collections.collections]}
    except Exception as exc:  # pragma: no cover - depends on external service
        LOGGER.warning("Qdrant health failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@app.get("/health/openai")
def health_openai() -> dict:
    return {"ok": bool(settings.openai_api_key), "has_key": bool(settings.openai_api_key)}


@app.post("/ingest/start")
def ingest_start(request: IngestRequest) -> dict:
    LOGGER.info("Ingest API called")
    result = _ingest.run(request)
    count = _ingest.upsert(result, request)
    return {"articles": count}


@app.post("/search", response_model=SearchResponse)
def search_endpoint(request: SearchRequest) -> SearchResponse:
    return _search.search(request)


@app.post("/tests/run", response_model=QualityReport)
def run_tests(request: TestRequest) -> QualityReport:
    return _tests.run(request)


@app.post("/chat")
def chat_endpoint(payload: dict) -> dict:
    messages = payload.get("messages", [])
    api_key = _store.data.openai_api_key or (settings.openai_api_key or "")
    client = get_client(api_key)
    text = client.chat(messages)
    return {"answer": text}


@app.websocket("/logs")
async def stream_logs(ws: WebSocket) -> AsyncIterator[None]:
    await ws.accept()
    await ws.send_json({"message": "Лог стрим пока работает в демо-режиме"})
    await ws.close()


__all__ = ["app"]
