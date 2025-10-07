"""HTTP-based helper for working with Qdrant."""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import httpx

LOGGER = logging.getLogger(__name__)

VECTOR_SIZE = 3072
COLLECTION_NAME = "legal_articles"


@dataclass
class VectorPayload:
    """Payload and vectors ready for upsert."""

    id_source: str
    title_vec: List[float]
    body_vec: List[float]
    payload: Dict[str, Any]

    @property
    def point_id(self) -> str:
        basis = self.id_source.encode("utf-8", "ignore")
        return hashlib.sha1(basis).hexdigest()


@dataclass
class ScoredPoint:
    """Simplified search result."""

    id: str
    score: float
    payload: Dict[str, Any]


class QdrantManager:
    """Minimal HTTP client that does not depend on gRPC bindings."""

    def __init__(
        self,
        url: str,
        api_key: Optional[str] = None,
        *,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = url.rstrip("/") or "http://localhost:6333"
        self.api_key = api_key
        self._client = httpx.Client(timeout=timeout, headers=self._headers())

    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        headers = {"content-type": "application/json"}
        if self.api_key:
            headers["api-key"] = self.api_key
        return headers

    def _request(self, method: str, path: str, *, json: Any = None, params: Dict[str, Any] | None = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        response = self._client.request(method, url, json=json, params=params)
        if response.status_code >= 400:
            raise RuntimeError(f"Qdrant request failed ({response.status_code}): {response.text}")
        if not response.text:
            return {}
        try:
            return response.json()
        except Exception as exc:  # pragma: no cover - unexpected payload
            raise RuntimeError(f"Invalid JSON from Qdrant: {response.text}") from exc

    # ------------------------------------------------------------------
    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    def list_collections(self) -> List[str]:
        data = self._request("GET", "/collections")
        return [item.get("name", "") for item in data.get("result", [])]

    # ------------------------------------------------------------------
    def collection_exists(self, name: str = COLLECTION_NAME) -> bool:
        try:
            self._request("GET", f"/collections/{name}")
            return True
        except RuntimeError as exc:
            if "404" in str(exc):
                return False
            raise

    # ------------------------------------------------------------------
    def ensure_collection(self, name: str = COLLECTION_NAME) -> None:
        if self.collection_exists(name):
            self._ensure_payload_indexes(name)
            return
        LOGGER.info("Creating Qdrant collection %s", name)
        body = {
            "vectors": {
                "title_vec": {"size": VECTOR_SIZE, "distance": "Cosine"},
                "body_vec": {"size": VECTOR_SIZE, "distance": "Cosine"},
            },
            "optimizers_config": {"default_segment_number": 2},
            "quantization_config": {"scalar": {"type": "int8", "always_ram": True}},
        }
        self._request("PUT", f"/collections/{name}", json=body)
        self._ensure_payload_indexes(name)

    # ------------------------------------------------------------------
    def _ensure_payload_indexes(self, name: str) -> None:
        try:
            info = self._request("GET", f"/collections/{name}")
            schema = (info.get("result") or {}).get("payload_schema", {})
        except RuntimeError:
            schema = {}
        desired: Dict[str, Any] = {
            "code": "keyword",
            "part": "keyword",
            "chapter": "keyword",
            "article": "keyword",
            "status": "keyword",
            "effective_from": "datetime",
            "effective_to": "datetime",
        }
        for field, field_type in desired.items():
            if field in schema:
                continue
            payload = {"field_schema": field_type}
            try:
                self._request("PUT", f"/collections/{name}/indexes/{field}", json=payload)
            except RuntimeError as exc:
                LOGGER.debug("Index creation for %s failed: %s", field, exc)
                continue

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
        batch: List[Dict[str, Any]] = []
        for payload in points:
            batch.append(
                {
                    "id": payload.point_id,
                    "vector": {"title_vec": payload.title_vec, "body_vec": payload.body_vec},
                    "payload": payload.payload,
                }
            )
            if len(batch) >= batch_size:
                self._flush_batch(name, batch)
                batch.clear()
        if batch:
            self._flush_batch(name, batch)

    def _flush_batch(self, name: str, batch: List[Dict[str, Any]]) -> None:
        self._request(
            "PUT",
            f"/collections/{name}/points",
            json={"points": batch},
            params={"wait": "true"},
        )

    # ------------------------------------------------------------------
    def search(
        self,
        query_vec: List[float],
        *,
        name: str = COLLECTION_NAME,
        vector_name: str = "body_vec",
        limit: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[ScoredPoint]:
        self.ensure_collection(name)
        body = {
            "vector": {"name": vector_name, "vector": query_vec},
            "limit": limit,
            "with_payload": True,
            "with_vectors": False,
        }
        if filters:
            body["filter"] = filters
        data = self._request("POST", f"/collections/{name}/points/search", json=body)
        points = []
        for entry in data.get("result", []):
            points.append(
                ScoredPoint(
                    id=str(entry.get("id")),
                    score=float(entry.get("score", 0.0)),
                    payload=dict(entry.get("payload") or {}),
                )
            )
        return points


__all__ = ["QdrantManager", "VectorPayload", "ScoredPoint", "VECTOR_SIZE", "COLLECTION_NAME"]
