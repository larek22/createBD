from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parents[2]))

from legal_rag_gui.utils.chunker import Chunker


def test_chunker_extracts_articles(tmp_path: Path) -> None:
    content = """
    Глава 1. Общие положения
    Статья 1. Первая статья
    Текст первой статьи.
    Статья 2. Вторая статья
    Текст второй статьи.
    """
    path = tmp_path / "doc.txt"
    path.write_text(content, "utf-8")

    chunker = Chunker()
    articles = chunker.parse_file(path)
    assert len(articles) == 2
    assert articles[0].identifier == "1"
    assert "Текст первой" in articles[0].body
