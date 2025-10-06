from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtWidgets

from ...utils.config import SettingsStore


class SettingsTab(QtWidgets.QWidget):
    settings_changed = QtCore.Signal(dict)
    connection_test_requested = QtCore.Signal()

    def __init__(self, settings: SettingsStore, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QtWidgets.QFormLayout(self)
        layout.addRow(QtWidgets.QLabel("<h2>Настройки</h2><p>Задай ключи и адреса один раз — приложение запомнит их.</p>"))

        self.openai_edit = QtWidgets.QLineEdit(self.settings.data.openai_api_key)
        self.openai_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.openai_edit.setToolTip("Ключ нужен для GPT-4.1 и GPT-5-nano. Мы сохраняем его только на твоём компьютере.")

        self.qdrant_url_edit = QtWidgets.QLineEdit(self.settings.data.qdrant_url)
        self.qdrant_url_edit.setToolTip("URL локального или облачного Qdrant. Например: http://localhost:6333")

        self.qdrant_key_edit = QtWidgets.QLineEdit(self.settings.data.qdrant_api_key)
        self.qdrant_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)

        self.docs_path_btn = QtWidgets.QPushButton(self.settings.data.documents_dir)
        self.docs_path_btn.clicked.connect(self._select_docs_dir)

        self.logs_path_btn = QtWidgets.QPushButton(self.settings.data.logs_dir)
        self.logs_path_btn.clicked.connect(self._select_logs_dir)

        self.theme_combo = QtWidgets.QComboBox()
        self.theme_combo.addItems(["dark", "light"])
        self.theme_combo.setCurrentText(self.settings.data.theme)

        self.test_button = QtWidgets.QPushButton("Тест подключения")
        self.test_button.clicked.connect(self.connection_test_requested.emit)

        layout.addRow("OpenAI API Key", self.openai_edit)
        layout.addRow("Qdrant URL", self.qdrant_url_edit)
        layout.addRow("Qdrant API Key", self.qdrant_key_edit)
        layout.addRow("Папка с документами", self.docs_path_btn)
        layout.addRow("Папка с логами", self.logs_path_btn)
        layout.addRow("Тема", self.theme_combo)
        layout.addRow(self.test_button)

        save_btn = QtWidgets.QPushButton("Сохранить настройки")
        save_btn.clicked.connect(self._save)
        layout.addRow(save_btn)

    def _select_docs_dir(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Выбери папку", self.settings.data.documents_dir)
        if path:
            self.docs_path_btn.setText(path)

    def _select_logs_dir(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "Куда писать логи", self.settings.data.logs_dir)
        if path:
            self.logs_path_btn.setText(path)

    def _save(self) -> None:
        data = {
            "openai_api_key": self.openai_edit.text(),
            "qdrant_url": self.qdrant_url_edit.text(),
            "qdrant_api_key": self.qdrant_key_edit.text(),
            "documents_dir": self.docs_path_btn.text(),
            "logs_dir": self.logs_path_btn.text(),
            "theme": self.theme_combo.currentText(),
        }
        self.settings.update(**data)
        self.settings_changed.emit(data)


__all__ = ["SettingsTab"]
