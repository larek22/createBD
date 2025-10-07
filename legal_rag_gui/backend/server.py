from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .ingest import ingest_file
from .search import search
from .store import Store
from .test_suite import run_quality_checks

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGER = logging.getLogger("legal_rag_backend")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "backend.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)


class Settings(BaseModel):
    data_path: Path = Field(default_factory=lambda: Path(__file__).resolve().parent.parent / "storage")
    qdrant_url: str = os.getenv("QDRANT_URL", "http://localhost:6333")
    openai_api_key: Optional[str] = os.getenv("OPENAI_API_KEY")


settings = Settings()
store = Store(settings.data_path)
app = FastAPI(title="Legal RAG Minimal Backend", version="1.0")


class IngestRequest(BaseModel):
    path: str
    code: str = "ГК РФ"
    title: str = "Гражданский кодекс Российской Федерации"
    part: Optional[str] = None


class SearchRequest(BaseModel):
    query: str
    limit: int = Field(default=5, ge=1, le=10)


@app.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "documents": len(store.list_records()),
        "qdrant_url": settings.qdrant_url,
        "has_openai_key": bool(settings.openai_api_key),
    }


@app.post("/ingest")
def ingest_endpoint(payload: IngestRequest) -> dict:
    path = Path(payload.path)
    if not path.exists():
        raise HTTPException(status_code=400, detail=f"File not found: {path}")
    stats = ingest_file(store, path=path, code=payload.code, title=payload.title, part=payload.part)
    return {"ok": True, "stats": stats}


@app.post("/search")
def search_endpoint(payload: SearchRequest) -> dict:
    results = search(store, payload.query, limit=payload.limit)
    return {"ok": True, "results": results}


@app.get("/quality")
def quality_endpoint() -> dict:
    report = run_quality_checks(store)
    return {"ok": True, "report": report}


__all__ = ["app", "store", "settings"]
