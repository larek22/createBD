from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from legal_rag_gui.backend.enrich import extract_keywords


def test_extract_keywords_filters_common_words():
    text = "Статья устанавливает право автора на произведение и защищает права"
    keywords = extract_keywords(text, topk=3)
    assert "автора" in keywords or "произведение" in keywords
