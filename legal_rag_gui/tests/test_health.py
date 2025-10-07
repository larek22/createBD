import pytest

pytest.importorskip("fastapi")

from legal_rag_gui.backend.server import health, health_openai


def test_health_endpoint():
    data = health()
    assert data.get("ok") is True


def test_openai_health_endpoint():
    data = health_openai()
    assert "ok" in data
