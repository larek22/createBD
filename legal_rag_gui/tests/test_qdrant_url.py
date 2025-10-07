from legal_rag_gui.backend.server import settings


def test_qdrant_url_default():
    assert settings.qdrant_url.startswith("http")
