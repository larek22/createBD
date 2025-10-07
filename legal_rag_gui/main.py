# --- make runnable both as module and as file ---
import os
import sys

if __package__ in (None, ""):
    sys.path.append(os.path.dirname(__file__))
    __package__ = "legal_rag_gui"
# ------------------------------------------------

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional

import requests
from PySide6 import QtCore, QtGui, QtWidgets

BACKEND_URL = os.getenv("LEGAL_RAG_BACKEND", "http://127.0.0.1:8765")


class LogPane(QtWidgets.QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)

    def log(self, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.appendPlainText(f"[{timestamp}] {message}")


class BackendClient(QtCore.QObject):
    error = QtCore.Signal(str)
    success = QtCore.Signal(str)
    searchResults = QtCore.Signal(list)
    healthStatus = QtCore.Signal(dict)

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, **kwargs):
        url = f"{self.base_url}{path}"
        try:
            response = requests.request(method, url, timeout=10, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            self.error.emit(f"Запрос {path} не удался: {exc}")
            return None

    @QtCore.Slot(str, str, str, object)
    def ingest(self, path: str, code: str, title: str, part: Optional[str]) -> None:
        payload = {"path": path, "code": code, "title": title, "part": part}
        data = self._request("post", "/ingest", json=payload)
        if data and data.get("ok"):
            stats = data.get("stats", {})
            self.success.emit(f"Индексация завершена: {stats}")

    @QtCore.Slot(str)
    def search(self, query: str) -> None:
        data = self._request("post", "/search", json={"query": query, "limit": 5})
        if data and data.get("ok"):
            self.searchResults.emit(data.get("results", []))

    @QtCore.Slot()
    def check_health(self) -> None:
        data = self._request("get", "/health")
        if data:
            self.healthStatus.emit(data)

    @QtCore.Slot()
    def run_quality(self) -> None:
        data = self._request("get", "/quality")
        if data and data.get("ok"):
            report = json.dumps(data.get("report", {}), ensure_ascii=False, indent=2)
            self.success.emit(f"Отчёт качества:\n{report}")


class IngestTab(QtWidgets.QWidget):
    def __init__(self, client: BackendClient, logger: LogPane) -> None:
        super().__init__()
        self.client = client
        self.logger = logger
        self.file_path: Optional[str] = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)

        self.path_label = QtWidgets.QLabel("Файл не выбран")
        btn_choose = QtWidgets.QPushButton("Выбрать документ…")
        btn_choose.clicked.connect(self._choose_file)

        form = QtWidgets.QFormLayout()
        self.code_edit = QtWidgets.QLineEdit("ГК РФ")
        self.title_edit = QtWidgets.QLineEdit("Гражданский кодекс РФ")
        self.part_edit = QtWidgets.QLineEdit()

        form.addRow("Кодекс:", self.code_edit)
        form.addRow("Название:", self.title_edit)
        form.addRow("Часть/раздел:", self.part_edit)

        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.hide()

        btn_index = QtWidgets.QPushButton("Начать индексацию")
        btn_index.clicked.connect(self._start_indexing)

        layout.addWidget(self.path_label)
        layout.addWidget(btn_choose)
        layout.addLayout(form)
        layout.addWidget(btn_index)
        layout.addWidget(self.progress)

    def _choose_file(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Выбор документа", str(Path.home()), "Документы (*.txt *.rtf)")
        if path:
            self.file_path = path
            self.path_label.setText(path)
            self.logger.log(f"Выбран файл: {path}")

    def _start_indexing(self) -> None:
        if not self.file_path:
            QtWidgets.QMessageBox.warning(self, "Нет файла", "Выберите документ для индексации")
            return
        self.progress.show()
        self.logger.log("Отправка файла на индексацию…")
        payload = (self.file_path, self.code_edit.text(), self.title_edit.text(), self.part_edit.text() or None)
        threading.Thread(target=self.client.ingest, args=payload, daemon=True).start()

    def indexing_finished(self) -> None:
        self.progress.hide()


class SearchTab(QtWidgets.QWidget):
    def __init__(self, client: BackendClient, logger: LogPane) -> None:
        super().__init__()
        self.client = client
        self.logger = logger
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        self.query_edit = QtWidgets.QLineEdit()
        self.query_edit.setPlaceholderText("Например: проценты по ст. 395")
        btn_search = QtWidgets.QPushButton("Искать")
        btn_search.clicked.connect(self._search)
        self.results = QtWidgets.QTextBrowser()

        layout.addWidget(self.query_edit)
        layout.addWidget(btn_search)
        layout.addWidget(self.results)

    def _search(self) -> None:
        query = self.query_edit.text().strip()
        if not query:
            return
        self.logger.log(f"Поиск: {query}")
        threading.Thread(target=self.client.search, args=(query,), daemon=True).start()

    def update_results(self, results: list) -> None:
        if not results:
            self.results.setHtml("<i>Ничего не найдено</i>")
            return
        parts = []
        for item in results:
            parts.append(
                f"<b>{item['title']}</b><br>Статья {item['article']} | Глава {item.get('chapter') or '—'}"
                f"<br><small>Источник: {item['source']}</small><br>"
                f"Оценка: {item['score']}<br>{item['summary']}<hr>"
            )
        self.results.setHtml("".join(parts))


class QualityTab(QtWidgets.QWidget):
    def __init__(self, client: BackendClient, logger: LogPane) -> None:
        super().__init__()
        self.client = client
        self.logger = logger
        layout = QtWidgets.QVBoxLayout(self)
        btn_run = QtWidgets.QPushButton("Запустить проверку базы")
        btn_run.clicked.connect(self._run)
        layout.addWidget(btn_run)

    def _run(self) -> None:
        self.logger.log("Запуск проверки качества…")
        threading.Thread(target=self.client.run_quality, daemon=True).start()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Legal RAG Studio — упрощённая версия")
        self.resize(900, 600)

        self.logger = LogPane()
        self.client = BackendClient(BACKEND_URL)

        tabs = QtWidgets.QTabWidget()
        self.ingest_tab = IngestTab(self.client, self.logger)
        self.search_tab = SearchTab(self.client, self.logger)
        self.quality_tab = QualityTab(self.client, self.logger)

        tabs.addTab(self.ingest_tab, "Создание базы")
        tabs.addTab(self.search_tab, "Поиск")
        tabs.addTab(self.quality_tab, "Проверка")

        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.addWidget(tabs)
        layout.addWidget(QtWidgets.QLabel("Лог действий:"))
        layout.addWidget(self.logger)
        self.setCentralWidget(container)

        # signals
        self.client.error.connect(self._on_error)
        self.client.success.connect(self._on_success)
        self.client.searchResults.connect(self.search_tab.update_results)
        self.client.healthStatus.connect(self._on_health)

        threading.Thread(target=self.client.check_health, daemon=True).start()

    @QtCore.Slot(str)
    def _on_error(self, message: str) -> None:
        self.logger.log(message)
        QtWidgets.QMessageBox.critical(self, "Ошибка", message)
        self.ingest_tab.indexing_finished()

    @QtCore.Slot(str)
    def _on_success(self, message: str) -> None:
        self.logger.log(message)
        self.ingest_tab.indexing_finished()

    @QtCore.Slot(dict)
    def _on_health(self, data: dict) -> None:
        msg = json.dumps(data, ensure_ascii=False)
        self.logger.log(f"Статус сервера: {msg}")


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
