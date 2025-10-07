"""Thin wrapper around qdrant-client with deterministic UUIDs."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional

try:  # pragma: no cover - optional dependency during tests
    from qdrant_client import QdrantClient
    from qdrant_client.http.models import (
        Distance,
        NamedVectorParams,
        OptimizersConfigDiff,
        PointStruct,
        ScalarQuantization,
        ScalarQuantizationConfig,
        ScalarType,
        VectorParams,
    )
except Exception:  # pragma: no cover
    QdrantClient = None  # type: ignore
    Distance = NamedVectorParams = OptimizersConfigDiff = PointStruct = ScalarQuantization = ScalarQuantizationConfig = ScalarType = VectorParams = None  # type: ignore

LOGGER = logging.getLogger(__name__)


VECTOR_SIZE = 3072
COLLECTION_NAME = "legal_articles"


@dataclass
class VectorPayload:
    id_source: str
    title_vec: List[float]
    body_vec: List[float]
    payload: dict

    @property
    def point_id(self) -> str:
        basis = self.id_source.encode("utf-8", "ignore")
        return hashlib.sha1(basis).hexdigest()


class QdrantManager:
    """Handles named-vector collections and payload indexing."""

    def __init__(self, url: str, api_key: str | None = None) -> None:
        if QdrantClient is None:
            raise RuntimeError("qdrant-client is required for vector operations")
        self.client = QdrantClient(url=url, api_key=api_key)

    # ------------------------------------------------------------------
    def ensure_collection(self, name: str = COLLECTION_NAME) -> None:
        if self.client.collection_exists(name):
            return
        LOGGER.info("Creating Qdrant collection %s", name)
        vectors_config = NamedVectorParams(
            {
                "title_vec": VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
                "body_vec": VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            }
        )
        quant = ScalarQuantization(
            scalar=ScalarQuantizationConfig(type=ScalarType.INT8, always_ram=True)
        )
        self.client.create_collection(
            collection_name=name,
            vectors_config=vectors_config,
            optimizers_config=OptimizersConfigDiff(default_segment_number=2),
            quantization_config=quant,
        )

    # ------------------------------------------------------------------
    def upsert(self, points: Iterable[VectorPayload], name: str = COLLECTION_NAME) -> None:
        self.upsert_batch(points, name=name)

    def upsert_batch(
        self,
        points: Iterable[VectorPayload],
        *,
        name: str = COLLECTION_NAME,
        batch_size: int = 512,
    ) -> None:
        self.ensure_collection(name)
        buffer: List[PointStruct] = []
        for payload in points:
            buffer.append(
                PointStruct(
                    id=payload.point_id,
                    vector={"title_vec": payload.title_vec, "body_vec": payload.body_vec},
                    payload=payload.payload,
                )
            )
            if len(buffer) >= batch_size:
                self.client.upsert(collection_name=name, wait=True, points=buffer)
                buffer.clear()
        if buffer:
            self.client.upsert(collection_name=name, wait=True, points=buffer)

    # ------------------------------------------------------------------
    def search(
        self,
        query_vec: List[float],
        *,
        name: str = COLLECTION_NAME,
        vector_name: str = "body_vec",
        limit: int = 5,
        filters: Optional[qm.Filter] = None,
    ) -> List[qm.ScoredPoint]:
        self.ensure_collection(name)
        return self.client.search(
            collection_name=name,
            query_vector=(vector_name, query_vec),
            limit=limit,
            with_payload=True,
            with_vectors=False,
            query_filter=filters,
        )


__all__ = ["QdrantManager", "VectorPayload", "VECTOR_SIZE", "COLLECTION_NAME"]
