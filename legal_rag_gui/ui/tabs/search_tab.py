from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class SearchTab(QtWidgets.QWidget):
    search_requested = QtCore.Signal(dict)
    ask_gpt_requested = QtCore.Signal(dict)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        headline = QtWidgets.QLabel(
            "<h2>Найди нужную норму</h2><p>Введи вопрос или номер статьи."
            " Программа покажет выдержки и может объяснить их простыми словами.</p>"
        )
        headline.setWordWrap(True)
        layout.addWidget(headline)

        form = QtWidgets.QHBoxLayout()
        self.query_edit = QtWidgets.QLineEdit()
        self.query_edit.setPlaceholderText("Например: ст. 395 проценты за пользование чужими денежными средствами")
        self.query_edit.returnPressed.connect(self._trigger_search)
        search_btn = QtWidgets.QPushButton("🔍 Найти")
        search_btn.clicked.connect(self._trigger_search)
        gpt_btn = QtWidgets.QPushButton("🤖 Спросить GPT-4.1")
        gpt_btn.clicked.connect(self._ask_gpt)
        gpt_btn.setToolTip("GPT использует найденные статьи, чтобы объяснить норму или ответить на вопрос.")
        form.addWidget(self.query_edit)
        form.addWidget(search_btn)
        form.addWidget(gpt_btn)
        layout.addLayout(form)

        self.results_browser = QtWidgets.QTextBrowser()
        self.results_browser.setPlaceholderText("Результаты появятся здесь. Каждая карточка содержит цитату и реквизиты.")
        layout.addWidget(self.results_browser)

        layout.addStretch(1)

    # ------------------------------------------------------------------
    def _trigger_search(self) -> None:
        text = self.query_edit.text().strip()
        if not text:
            return
        self.search_requested.emit({"query": text, "top_k": 5})

    def _ask_gpt(self) -> None:
        text = self.query_edit.text().strip()
        if not text:
            return
        self.ask_gpt_requested.emit({"query": text})

    # ------------------------------------------------------------------
    def show_results(self, results: list[dict]) -> None:
        if not results:
            self.results_browser.setHtml("<p>Ничего не найдено. Попробуйте переформулировать запрос.</p>")
            return
        html_parts = []
        for item in results:
            title = item.get("title", "Без названия")
            article = item.get("article", "—")
            summary = item.get("summary", "")
            text = item.get("text", "")[:600]
            score = item.get("score", 0.0)
            html_parts.append(
                f"<div style='border:1px solid #555;border-radius:8px;padding:10px;margin:6px 0;'>"
                f"<b>{title}</b> · Статья {article} · Score: {score:.3f}<br>"
                f"<i>{summary}</i><br><pre style='white-space:pre-wrap;font-family:inherit'>{text}</pre></div>"
            )
        self.results_browser.setHtml("".join(html_parts))

    def show_gpt_answer(self, answer: str) -> None:
        self.results_browser.append("<hr><h3>Ответ GPT</h3>")
        self.results_browser.append(f"<div style='white-space:pre-wrap'>{answer}</div>")


__all__ = ["SearchTab"]
