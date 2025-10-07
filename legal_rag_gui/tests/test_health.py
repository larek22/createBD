import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from legal_rag_gui.backend.server import app


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
