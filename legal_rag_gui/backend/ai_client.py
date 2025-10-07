"""Shared OpenAI helper with graceful fallbacks."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import List, Sequence

try:  # pragma: no cover - optional dependency in tests
    import httpx
except Exception:  # pragma: no cover
    httpx = None

LOGGER = logging.getLogger(__name__)


class OpenAIManager:
    """Wraps REST calls so the rest of the app can be agnostic of the vendor SDK."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1") -> None:
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        if httpx and self.api_key:
            self._client = httpx.Client(timeout=30.0, headers={"Authorization": f"Bearer {self.api_key}"})
        else:
            self._client = None

    # ------------------------------------------------------------------
    def _post(self, path: str, payload: dict) -> dict:
        if not self._client:
            LOGGER.warning("OpenAIManager: no API key configured – returning mock response")
            return {"choices": [{"message": {"content": "(offline mode)"}}]}
        response = self._client.post(f"{self.base_url}{path}", json=payload) if self._client else None
        if response is None:
            return {"choices": [{"message": {"content": "(offline mode)"}}]}
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    def embed(self, texts: Sequence[str], model: str = "text-embedding-3-large") -> List[List[float]]:
        payload = {"input": list(texts), "model": model}
        data = self._post("/embeddings", payload)
        if "data" not in data:
            return [[0.0] * 3072 for _ in texts]
        vectors = [item.get("embedding", [0.0] * 3072) for item in data.get("data", [])]
        if not vectors:
            vectors = [[0.0] * 3072 for _ in texts]
        return vectors

    def summarize(self, text: str, *, model: str = "gpt-4.1-mini") -> str:
        prompt = (
            "Сделай короткую (≤160 символов) аннотацию нормы. Без вводных слов,"
            " только суть."
        )
        data = self._post(
            "/chat/completions",
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompt},
                    {"role": "user", "content": text[:1500]},
                ],
                "temperature": 0,
            },
        )
        try:
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""

    def chat(self, messages: Sequence[dict], *, model: str = "gpt-4.1") -> str:
        data = self._post(
            "/chat/completions",
            {
                "model": model,
                "messages": list(messages),
                "temperature": 0.1,
            },
        )
        try:
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return ""


@lru_cache(maxsize=4)
def get_client(api_key: str) -> OpenAIManager:
    return OpenAIManager(api_key)


__all__ = ["OpenAIManager", "get_client"]
