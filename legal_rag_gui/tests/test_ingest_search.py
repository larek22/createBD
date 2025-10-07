from pathlib import Path

from legal_rag_gui.backend.ingest import ingest_file
from legal_rag_gui.backend.search import search
from legal_rag_gui.backend.store import Store


def test_ingest_and_search(tmp_path: Path) -> None:
    storage = tmp_path / "storage"
    store = Store(storage)

    sample = tmp_path / "doc.txt"
    sample.write_text(
        """Глава 1
Статья 1. Общие положения
Это первая статья.

Статья 2. Дополнительно
Текст второй статьи.""",
        encoding="utf-8",
    )

    stats = ingest_file(store, path=sample, code="ГК РФ", title="Тестовый документ", part=None)
    assert stats["articles"] == 2

    results = search(store, "первая статья")
    assert results, "должен быть хотя бы один результат"
    assert results[0]["article"] in {"1", "2"}
