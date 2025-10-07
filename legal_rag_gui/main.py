from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass
from typing import Any, Callable

if __package__ in (None, ""):
    sys.path.append(os.path.dirname(__file__))
    __package__ = "legal_rag_gui"

import httpx
from PySide6 import QtCore, QtGui, QtWidgets

from backend import server  # ensures FastAPI app is importable when uvicorn runs
from .utils.backend_launcher import BackendProcessManager
from .utils.config import SettingsStore
from .utils.logger import configure_logging
from .ui.tabs.create_base_tab import CreateBaseTab
from .ui.tabs.search_tab import SearchTab
from .ui.tabs.test_tab import TestTab
from .ui.tabs.settings_tab import SettingsTab
from .ui.tabs.chat_tab import ChatTab

LOGGER = logging.getLogger(__name__)


@dataclass
class BackendSettings:
    url: str


class BackendClient(QtCore.QObject):
    ingest_finished = QtCore.Signal(int)
    ingest_failed = QtCore.Signal(str)
    search_ready = QtCore.Signal(list)
    search_failed = QtCore.Signal(str)
    tests_ready = QtCore.Signal(dict)
    tests_failed = QtCore.Signal(str)
    chat_ready = QtCore.Signal(str)
    chat_failed = QtCore.Signal(str)
    health_ready = QtCore.Signal(dict)
    health_failed = QtCore.Signal(str)

    def __init__(self, settings: SettingsStore, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.base_url = f"http://127.0.0.1:{self.settings.data.last_backend_port}"
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=60.0)

    async def _post(self, path: str, payload: dict) -> httpx.Response:
        return await self._client.post(path, json=payload)

    async def _get(self, path: str) -> httpx.Response:
        return await self._client.get(path)

    async def ingest(self, payload: dict) -> None:
        try:
            resp = await self._post("/ingest/start", payload)
            resp.raise_for_status()
            data = resp.json()
            self.ingest_finished.emit(int(data.get("articles", 0)))
        except Exception as exc:  # pragma: no cover - network errors are environment specific
            self.ingest_failed.emit(str(exc))

    async def search(self, payload: dict) -> None:
        try:
            resp = await self._post("/search", payload)
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            self.search_ready.emit(items)
        except Exception as exc:
            self.search_failed.emit(str(exc))

    async def run_tests(self, payload: dict) -> None:
        try:
            resp = await self._post("/tests/run", payload)
            resp.raise_for_status()
            self.tests_ready.emit(resp.json())
        except Exception as exc:
            self.tests_failed.emit(str(exc))

    async def ask_chat(self, payload: dict) -> None:
        try:
            messages = [
                {"role": "system", "content": f"Режим: {payload.get('mode')}"},
                {"role": "user", "content": payload.get("prompt", "")},
            ]
            resp = await self._post("/chat", {"messages": messages})
            resp.raise_for_status()
            data = resp.json()
            self.chat_ready.emit(data.get("answer", ""))
        except Exception as exc:
            self.chat_failed.emit(str(exc))

    async def check_health(self) -> None:
        try:
            backend_resp = await self._get("/health")
            backend_resp.raise_for_status()
            qdrant_resp = await self._get("/health/qdrant")
            qdrant_resp.raise_for_status()
            openai_resp = await self._get("/health/openai")
            openai_resp.raise_for_status()
            data = {
                "backend": backend_resp.json(),
                "qdrant": qdrant_resp.json(),
                "openai": openai_resp.json(),
            }
            self.health_ready.emit(data)
        except Exception as exc:
            self.health_failed.emit(str(exc))


class AsyncTask(QtCore.QRunnable):
    def __init__(self, coro: Callable[[], Any]) -> None:
        super().__init__()
        self.coro = coro

    @QtCore.Slot()
    def run(self) -> None:
        asyncio.run(self.coro())


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        configure_logging()
        self.settings = SettingsStore()
        self.backend_manager = BackendProcessManager(self.settings)
        self.backend = BackendClient(self.settings)
        self.pool = QtCore.QThreadPool.globalInstance()

        self.setWindowTitle("Legal RAG Studio")
        self.resize(1280, 780)
        self._setup_ui()
        self._connect_signals()
        QtCore.QTimer.singleShot(0, self._ensure_backend_running)

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        wrapper = QtWidgets.QWidget()
        self.setCentralWidget(wrapper)
        layout = QtWidgets.QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)

        # Navigation list
        self.nav = QtWidgets.QListWidget()
        self.nav.setFixedWidth(200)
        self.nav.addItems([
            "Главная",
            "Поиск",
            "Тесты",
            "Настройки",
            "GPT ассистент",
        ])
        self.nav.setCurrentRow(0)
        layout.addWidget(self.nav)

        # Stacked pages
        self.stack = QtWidgets.QStackedWidget()
        layout.addWidget(self.stack, 1)

        self.create_tab = CreateBaseTab(self.settings)
        self.search_tab = SearchTab()
        self.test_tab = TestTab()
        self.settings_tab = SettingsTab(self.settings)
        self.chat_tab = ChatTab()

        self.stack.addWidget(self.create_tab)
        self.stack.addWidget(self.search_tab)
        self.stack.addWidget(self.test_tab)
        self.stack.addWidget(self.settings_tab)
        self.stack.addWidget(self.chat_tab)

        # Log panel at bottom
        dock = QtWidgets.QDockWidget("Логи", self)
        dock.setAllowedAreas(QtCore.Qt.BottomDockWidgetArea)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        dock.setWidget(self.log_box)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

    def _connect_signals(self) -> None:
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.create_tab.ingest_requested.connect(self._start_ingest)
        self.search_tab.search_requested.connect(self._start_search)
        self.search_tab.ask_gpt_requested.connect(self._start_search_gpt)
        self.test_tab.tests_requested.connect(self._start_tests)
        self.settings_tab.settings_changed.connect(lambda data: self.log_box.appendPlainText("Настройки сохранены."))
        self.settings_tab.connection_test_requested.connect(self._test_connections)
        self.chat_tab.ask_chat.connect(self._start_chat)

        self.backend.ingest_finished.connect(self._ingest_done)
        self.backend.ingest_failed.connect(lambda err: self.log_box.appendPlainText(f"Ошибка индексации: {err}"))
        self.backend.search_ready.connect(self.search_tab.show_results)
        self.backend.search_failed.connect(lambda err: self.log_box.appendPlainText(f"Ошибка поиска: {err}"))
        self.backend.tests_ready.connect(self.test_tab.show_report)
        self.backend.tests_failed.connect(lambda err: self.log_box.appendPlainText(f"Ошибка тестов: {err}"))
        self.backend.chat_ready.connect(self.chat_tab.show_answer)
        self.backend.chat_failed.connect(lambda err: self.log_box.appendPlainText(f"Ошибка GPT: {err}"))
        self.backend.health_ready.connect(self._show_health)
        self.backend.health_failed.connect(lambda err: self.log_box.appendPlainText(f"❌ Проверка не прошла: {err}"))

    # ------------------------------------------------------------------
    def _submit(self, coro: Callable[[], Any]) -> None:
        task = AsyncTask(coro)
        self.pool.start(task)

    def _ensure_backend_running(self) -> None:
        self.log_box.appendPlainText("⏳ Проверяем подключение…")
        if self.backend_manager.ensure_running():
            self.log_box.appendPlainText(f"✅ Backend запущен на {self.backend_manager.base_url}")
        else:
            self.log_box.appendPlainText("❌ Не удалось запустить backend. Проверьте настройки и логи.")

    def _start_ingest(self, payload: dict) -> None:
        self.log_box.appendPlainText("→ Отправляем задания на backend…")
        self._submit(lambda: self.backend.ingest(payload))

    def _start_search(self, payload: dict) -> None:
        self._submit(lambda: self.backend.search(payload))

    def _start_search_gpt(self, payload: dict) -> None:
        self._submit(lambda: self.backend.search(payload))
        self.chat_tab.ask_chat.emit({"mode": "Пояснение", "prompt": payload["query"]})

    def _start_tests(self, payload: dict) -> None:
        self._submit(lambda: self.backend.run_tests(payload))

    def _start_chat(self, payload: dict) -> None:
        self._submit(lambda: self.backend.ask_chat(payload))

    def _ingest_done(self, count: int) -> None:
        self.create_tab.handle_ingest_complete(count)
        self.log_box.appendPlainText(f"Готово: {count} записей.")

    def _test_connections(self) -> None:
        if not self.backend_manager.ensure_running():
            self.log_box.appendPlainText("❌ Backend недоступен. Проверьте лог backend.log")
            return
        self.log_box.appendPlainText("⏳ Проверяем подключение…")
        self._submit(lambda: self.backend.check_health())

    def _show_health(self, data: dict) -> None:
        backend = data.get("backend", {})
        qdrant = data.get("qdrant", {})
        openai = data.get("openai", {})
        self.log_box.appendPlainText(
            "✅ Backend отвечает: " + ("ok" if backend.get("ok", True) else str(backend))
        )
        if qdrant.get("ok"):
            collections = ", ".join(qdrant.get("collections", []) or []) or "нет коллекций"
            self.log_box.appendPlainText(f"✅ Qdrant готов ({collections})")
        else:
            self.log_box.appendPlainText(f"❌ Qdrant: {qdrant.get('error', 'неизвестная ошибка')}")
        if openai.get("ok"):
            self.log_box.appendPlainText("✅ OpenAI ключ найден")
        else:
            self.log_box.appendPlainText("⚠️ OpenAI ключ не задан — GPT-функции будут ограничены")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # pragma: no cover - GUI shutdown
        self.backend_manager.shutdown()
        super().closeEvent(event)


def main() -> int:
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Legal RAG Studio")
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#10131a"))
    palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor("#f8f8f8"))
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#1b202c"))
    palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor("#242b3a"))
    palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.Button, QtGui.QColor("#2f3b52"))
    palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor("#ffffff"))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#4f9dff"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#000000"))
    app.setPalette(palette)
    font = QtGui.QFont("Segoe UI", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover - GUI entry point
    sys.exit(main())
