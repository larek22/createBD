"""FastAPI application used by the PySide6 GUI."""
from __future__ import annotations

import logging
from typing import AsyncIterator

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from ..utils.config import SettingsStore
from ..utils.logger import configure_logging
from .ingest import IngestRequest, IngestService
from .search import SearchRequest, SearchService
from .test_suite import QualityReport, TestRequest, TestService
from .ai_client import get_client

configure_logging()
LOGGER = logging.getLogger(__name__)

app = FastAPI(title="Legal RAG Studio Backend", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_settings = SettingsStore()
_ingest = IngestService(_settings)
_search = SearchService(_settings)
_tests = TestService(_settings)


@app.get("/status")
def status() -> dict:
    return {"status": "ok"}


@app.post("/ingest/start")
def ingest_start(request: IngestRequest) -> dict:
    LOGGER.info("Ingest API called")
    result = _ingest.run(request)
    count = _ingest.upsert(result, request)
    return {"articles": count}


@app.post("/search", response_model=QualityReport, response_model_exclude_none=True)
def search_endpoint(request: SearchRequest):  # type: ignore[override]
    response = _search.search(request)
    return {"created_at": "", "summary": "", "cases": [{"name": item.get("article", ""), "status": "match", "score": item.get("score", 0.0), "details": item.get("summary", "") } for item in response.items]}


@app.post("/tests/run", response_model=QualityReport)
def run_tests(request: TestRequest) -> QualityReport:
    return _tests.run(request)


@app.post("/chat")
def chat_endpoint(payload: dict) -> dict:
    messages = payload.get("messages", [])
    client = get_client(_settings.data.openai_api_key)
    text = client.chat(messages)
    return {"answer": text}


@app.websocket("/logs")
async def stream_logs(ws: WebSocket) -> AsyncIterator[None]:
    await ws.accept()
    await ws.send_json({"message": "Лог стрим пока работает в демо-режиме"})
    await ws.close()


__all__ = ["app"]
