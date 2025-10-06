"""Ingestion orchestration for Legal RAG Studio."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from pydantic import BaseModel

from ..db.qdrant_client import QdrantManager, VectorPayload
from ..utils.chunker import Article, Chunker
from ..utils.config import SettingsStore
from .ai_client import get_client
from .enrich import enrich_articles

LOGGER = logging.getLogger(__name__)


class IngestRequest(BaseModel):
    files: List[str]
    code: str
    title: str
    version: str | None = None
    auto_articles: bool = True
    use_gpt_summaries: bool = True
    append_mode: bool = True


@dataclass
class IngestResult:
    articles: List[Article]
    enriched: List[dict]


class IngestService:
    def __init__(self, settings: SettingsStore | None = None) -> None:
        self.settings = settings or SettingsStore()

    # ------------------------------------------------------------------
    def run(self, request: IngestRequest) -> IngestResult:
        LOGGER.info("Starting ingest for %d files", len(request.files))
        chunker = Chunker(auto_articles=request.auto_articles)
        articles: List[Article] = []
        for file in request.files:
            path = Path(file)
            LOGGER.info("Parsing %s", path)
            articles.extend(chunker.parse_file(path))
        LOGGER.info("Parsed %d articles", len(articles))

        enriched: List[dict] = []
        if request.use_gpt_summaries:
            client = get_client(self.settings.data.openai_api_key)
            enriched = enrich_articles(client, [a.body for a in articles])
        else:
            enriched = [{"summary": a.body[:160], "keywords": []} for a in articles]
        return IngestResult(articles=articles, enriched=enriched)

    # ------------------------------------------------------------------
    def upsert(self, result: IngestResult, request: IngestRequest) -> int:
        qdrant = QdrantManager(self.settings.data.qdrant_url, self.settings.data.qdrant_api_key or None)
        client = get_client(self.settings.data.openai_api_key)
        texts = [article.body for article in result.articles]
        titles = [article.heading for article in result.articles]
        LOGGER.info("Creating embeddings for %d articles", len(texts))
        body_vecs = client.embed(texts)
        title_vecs = client.embed(titles)
        payloads: Iterable[VectorPayload] = []
        items: List[VectorPayload] = []
        for article, bvec, tvec, enrich in zip(result.articles, body_vecs, title_vecs, result.enriched):
            payload = article.to_payload(code=request.code, title=request.title, source=Path(request.files[0]))
            payload.update(enrich)
            payload.update({"version": request.version or "", "append_mode": request.append_mode})
            items.append(VectorPayload(id_source=f"{request.code}:{article.identifier}:{article.chapter}", title_vec=tvec, body_vec=bvec, payload=payload))
        payloads = items
        qdrant.upsert(payloads)
        LOGGER.info("Upserted %d points", len(items))
        return len(items)


__all__ = ["IngestRequest", "IngestService", "IngestResult"]
