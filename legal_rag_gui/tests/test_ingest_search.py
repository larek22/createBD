import json
from pathlib import Path

import pytest

pytest.importorskip("pydantic")

from legal_rag_gui.backend.ingest import IngestRequest, IngestService
from legal_rag_gui.backend.search import SearchRequest, SearchService
from legal_rag_gui.utils.config import SettingsStore


class StubAI:
    def embed(self, texts, model="text-embedding-3-large"):
        def encode(text: str) -> list[float]:
            base = (sum(ord(c) for c in text) % 1000) / 1000.0
            return [base] * 3072

        return [encode(text) for text in texts]

    def summarize(self, text: str, model: str = "gpt-4.1-mini") -> str:
        return text[:60]

    def chat(self, messages, model: str = "gpt-4.1-mini") -> str:
        return json.dumps({"scores": [{"index": 1, "score": 99.0}]})


class FakePoint:
    def __init__(self, payload: dict):
        self.payload = payload
        self.id = payload.get("chunk_id") or payload.get("article")


class StubQdrant:
    storage: list[dict] = []

    def __init__(self, url: str, api_key: str | None = None) -> None:
        self.url = url
        self.api_key = api_key

    def ensure_collection(self, name: str = "legal_articles") -> None:
        return

    def upsert_batch(self, points, name: str = "legal_articles", batch_size: int = 512):
        for item in points:
            record = {
                "payload": item.payload,
                "title_vec": item.title_vec,
                "body_vec": item.body_vec,
            }
            self.__class__.storage.append(record)

    def search(self, query_vec, *, name="legal_articles", vector_name="body_vec", limit=5, filters=None):
        def score(record: dict) -> float:
            vec = record[f"{vector_name}"]
            return sum(q * v for q, v in zip(query_vec, vec))

        ranked = sorted(self.storage, key=score, reverse=True)[:limit]
        return [FakePoint(record["payload"]) for record in ranked]


@pytest.fixture(autouse=True)
def reset_storage(monkeypatch):
    StubQdrant.storage = []
    monkeypatch.setattr("legal_rag_gui.backend.ingest.QdrantManager", StubQdrant)
    monkeypatch.setattr("legal_rag_gui.backend.search.QdrantManager", StubQdrant)
    stub_ai = StubAI()
    monkeypatch.setattr("legal_rag_gui.backend.ingest.get_client", lambda *_: stub_ai)
    monkeypatch.setattr("legal_rag_gui.backend.search.get_client", lambda *_: stub_ai)
    monkeypatch.setattr(
        "legal_rag_gui.backend.ingest.enrich_articles",
        lambda manager, texts: [{"summary": text[:40], "keywords": ["ключ"]} for text in texts],
    )
    yield


def test_end_to_end_ingest_and_search(tmp_path):
    config_path = tmp_path / "config.yaml"
    store = SettingsStore(config_path)
    store.update(openai_api_key="stub", qdrant_url="http://fake")

    sample_text = """
    Глава 1. Общие положения
    Статья 395. Ответственность за пользование чужими денежными средствами
    Должник обязан уплатить проценты за пользование чужими денежными средствами.
    """.strip()
    source = tmp_path / "gk_part.txt"
    source.write_text(sample_text, "utf-8")

    ingest = IngestService(store)
    request = IngestRequest(
        files=[str(source)],
        code="ГК РФ",
        title="Гражданский кодекс",
        version="ред. 2024",
        auto_articles=True,
        use_gpt_summaries=True,
        append_mode=True,
    )

    result = ingest.run(request)
    count = ingest.upsert(result, request)
    assert count > 0

    search = SearchService(store)
    response = search.search(SearchRequest(query="ст. 395", top_k=3))
    assert response.items, "Поиск должен вернуть хотя бы один результат"
    top = response.items[0]
    assert "395" in top.get("citation", "")
    assert top.get("code") == "ГК РФ"
