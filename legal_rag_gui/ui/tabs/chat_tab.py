from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class ChatTab(QtWidgets.QWidget):
    ask_chat = QtCore.Signal(dict)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "<h2>GPT-ассистент</h2><p>Спроси про норму, попроси объяснить или составить черновик документа.</p>"
        ))

        mode_layout = QtWidgets.QHBoxLayout()
        mode_layout.addWidget(QtWidgets.QLabel("Режим:"))
        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItems(["Пояснение", "Анализ нормы", "Составление документа"])
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch(1)
        layout.addLayout(mode_layout)

        self.prompt_edit = QtWidgets.QPlainTextEdit()
        self.prompt_edit.setPlaceholderText("Например: Объясни простыми словами ст. 395 ГК РФ")
        layout.addWidget(self.prompt_edit)

        ask_btn = QtWidgets.QPushButton("Спросить")
        ask_btn.clicked.connect(self._emit_question)
        layout.addWidget(ask_btn)

        self.answer_view = QtWidgets.QTextBrowser()
        self.answer_view.setPlaceholderText("Ответ GPT появится здесь. Его можно выделить и скопировать.")
        layout.addWidget(self.answer_view)

    def _emit_question(self) -> None:
        text = self.prompt_edit.toPlainText().strip()
        if not text:
            return
        self.answer_view.setHtml("<p>🤖 Генерирую ответ…</p>")
        self.ask_chat.emit({"mode": self.mode_combo.currentText(), "prompt": text})

    def show_answer(self, answer: str) -> None:
        self.answer_view.setHtml(f"<div style='white-space:pre-wrap'>{answer}</div>")


__all__ = ["ChatTab"]
