from __future__ import annotations

from PySide6 import QtCore, QtWidgets


class TestTab(QtWidgets.QWidget):
    tests_requested = QtCore.Signal(dict)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "<h2>Проверка качества базы</h2><p>Один клик запускает автоматические тесты:"
            " количество статей, корректность метаданных и оценку релевантности через GPT-4.1.</p>"
        ))
        self.limit_spin = QtWidgets.QSpinBox()
        self.limit_spin.setRange(1, 100)
        self.limit_spin.setValue(10)
        self.limit_spin.setToolTip("Сколько вопросов взять для проверки. Больше — дольше, но точнее.")
        run_btn = QtWidgets.QPushButton("Запустить автотест базы")
        run_btn.clicked.connect(self._run_tests)

        control_layout = QtWidgets.QHBoxLayout()
        control_layout.addWidget(QtWidgets.QLabel("Количество тестов:"))
        control_layout.addWidget(self.limit_spin)
        control_layout.addStretch(1)
        control_layout.addWidget(run_btn)
        layout.addLayout(control_layout)

        self.results = QtWidgets.QTextBrowser()
        self.results.setPlaceholderText("Здесь появится отчёт: зелёные галочки, предупреждения и ссылки на проблемные запросы.")
        layout.addWidget(self.results)

    def _run_tests(self) -> None:
        self.results.setHtml("<p>⏳ Тесты запущены…</p>")
        self.tests_requested.emit({"limit": self.limit_spin.value()})

    def show_report(self, report: dict) -> None:
        cases = report.get("cases", [])
        summary = report.get("summary", "")
        html = [f"<h3>Краткий итог</h3><p>{summary}</p>"]
        html.append("<ul>")
        for case in cases:
            badge = "✅" if case.get("status") == "pass" else "⚠️"
            html.append(f"<li>{badge} {case.get('name')} — {case.get('details')}</li>")
        html.append("</ul>")
        self.results.setHtml("".join(html))


__all__ = ["TestTab"]
