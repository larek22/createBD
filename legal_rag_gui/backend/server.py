"""FastAPI application used by the PySide6 GUI."""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ..utils.config import SettingsStore
from ..utils.logger import configure_logging
from ..db.qdrant_client import QdrantManager
from .ai_client import get_client
from .ingest import IngestRequest, IngestService
from .search import SearchRequest, SearchResponse, SearchService
from .test_suite import QualityReport, TestRequest, TestService


_store = SettingsStore()


class Settings(BaseModel):
    qdrant_url: str = os.getenv("QDRANT_URL", _store.data.qdrant_url or "http://localhost:6333")
    qdrant_api_key: str | None = os.getenv("QDRANT_API_KEY") or (_store.data.qdrant_api_key or None)
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or (_store.data.openai_api_key or None)
    app_port: int = int(os.getenv("APP_PORT", str(_store.data.last_backend_port or 8765)))


log_path = configure_logging()
LOGGER = logging.getLogger(__name__)

settings = Settings()
LOGGER.info("Backend starting. Logs: %s", log_path)
LOGGER.info("Configured Qdrant URL: %s", settings.qdrant_url)
LOGGER.info("OpenAI key present: %s", bool(settings.openai_api_key))

_store.update(
    qdrant_url=settings.qdrant_url,
    qdrant_api_key=settings.qdrant_api_key or "",
    openai_api_key=settings.openai_api_key or "",
    last_backend_port=settings.app_port,
)

app = FastAPI(title="Legal RAG Studio Backend", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_ingest = IngestService(_store)
_search = SearchService(_store)
_tests = TestService(_store)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "qdrant_url": settings.qdrant_url}


@app.get("/health/qdrant")
def health_qdrant() -> dict:
    manager: QdrantManager | None = None
    try:
        manager = QdrantManager(settings.qdrant_url, settings.qdrant_api_key or None)
        collections = manager.list_collections()
        return {"ok": True, "collections": collections}
    except Exception as exc:  # pragma: no cover - depends on external service
        LOGGER.warning("Qdrant health failed: %s", exc)
        return {"ok": False, "error": str(exc)}
    finally:
        if manager is not None:
            try:
                manager.close()
            except Exception:  # pragma: no cover - best effort cleanup
                pass


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
