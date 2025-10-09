from __future__ import annotations

from pathlib import Path
from typing import Callable, List

from PySide6 import QtCore, QtGui, QtWidgets

from ...utils.config import SettingsStore


class CreateBaseTab(QtWidgets.QWidget):
    ingest_requested = QtCore.Signal(dict)

    def __init__(self, settings: SettingsStore, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._files: List[str] = []
        self._setup_ui()

    # ------------------------------------------------------------------
    def _setup_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        hero = QtWidgets.QLabel(
            "<h2>Создай новую юридическую базу</h2><p>Добавь документы и нажми старт."
            " Все шаги сопровождаются подсказками – подойдёт даже новичку.</p>"
        )
        hero.setWordWrap(True)
        layout.addWidget(hero)

        # File selection
        file_box = QtWidgets.QGroupBox("1. Добавь документы")
        file_layout = QtWidgets.QVBoxLayout(file_box)
        self.files_list = QtWidgets.QListWidget()
        file_buttons = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("+ Добавить документ")
        add_btn.setToolTip("Выбирай файлы .rtf, .pdf, .docx или .txt. Их можно добавлять по одному или сразу несколько.")
        add_btn.clicked.connect(self._pick_files)
        clear_btn = QtWidgets.QPushButton("Очистить список")
        clear_btn.clicked.connect(self._clear_files)
        file_buttons.addWidget(add_btn)
        file_buttons.addWidget(clear_btn)
        file_layout.addLayout(file_buttons)
        file_layout.addWidget(self.files_list)
        layout.addWidget(file_box)

        # Metadata form
        form_box = QtWidgets.QGroupBox("2. Заполни данные (нужно для поиска и отчётов)")
        form_layout = QtWidgets.QFormLayout(form_box)
        self.title_edit = QtWidgets.QLineEdit()
        self.title_edit.setPlaceholderText("Гражданский кодекс Российской Федерации")
        self.code_edit = QtWidgets.QComboBox()
        self.code_edit.addItems(["ГК РФ", "УК РФ", "КоАП РФ", "Трудовой кодекс"])
        self.version_edit = QtWidgets.QLineEdit()
        self.version_edit.setPlaceholderText("например: ред. от 01.03.2024")

        self.auto_chunk = QtWidgets.QCheckBox("Автоматически находить статьи и главы")
        self.auto_chunk.setChecked(True)
        self.auto_chunk.setToolTip("Оставь включённым, чтобы программа сама разбила документ на статьи.")
        self.gpt_summary = QtWidgets.QCheckBox("Создавать аннотации GPT-4.1-mini")
        self.gpt_summary.setChecked(True)
        self.gpt_summary.setToolTip(
            "Включи, чтобы модель GPT-4.1-mini написала короткие резюме и ключевые фразы к каждой статье."
        )
        self.append_mode = QtWidgets.QCheckBox("Добавить к существующей базе")
        self.append_mode.setChecked(True)
        self.append_mode.setToolTip("Выключи, если хочешь собрать базу заново и не смешивать со старой.")

        form_layout.addRow("Название документа", self.title_edit)
        form_layout.addRow("Кодекс", self.code_edit)
        form_layout.addRow("Версия / дата", self.version_edit)
        form_layout.addRow(self.auto_chunk)
        form_layout.addRow(self.gpt_summary)
        form_layout.addRow(self.append_mode)
        layout.addWidget(form_box)

        # Action button
        self.start_btn = QtWidgets.QPushButton("Начать индексацию")
        self.start_btn.clicked.connect(self._request_ingest)
        self.start_btn.setEnabled(False)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setRange(0, 100)
        self.log_box = QtWidgets.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setPlaceholderText("Здесь появятся шаги: парсинг, аннотации, индексация…")
        layout.addWidget(self.start_btn)
        layout.addWidget(self.progress)
        layout.addWidget(self.log_box)
        layout.addStretch(1)

    # ------------------------------------------------------------------
    def _pick_files(self) -> None:
        start_dir = Path(self.settings.data.documents_dir)
        files, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Выбери документы", str(start_dir), "Документы (*.rtf *.pdf *.docx *.txt)")
        if files:
            self._files.extend(files)
            for file in files:
                self.files_list.addItem(file)
            self.start_btn.setEnabled(True)

    def _clear_files(self) -> None:
        self._files.clear()
        self.files_list.clear()
        self.start_btn.setEnabled(False)

    def _request_ingest(self) -> None:
        if not self._files:
            return
        payload = {
            "files": self._files,
            "code": self.code_edit.currentText(),
            "title": self.title_edit.text() or self.code_edit.currentText(),
            "version": self.version_edit.text(),
            "auto_articles": self.auto_chunk.isChecked(),
            "use_gpt_summaries": self.gpt_summary.isChecked(),
            "append_mode": self.append_mode.isChecked(),
        }
        self.log_box.appendPlainText("▶ Запуск индексации…")
        self.progress.setValue(5)
        self.ingest_requested.emit(payload)

    # ------------------------------------------------------------------
    def handle_ingest_progress(self, step: str, value: int) -> None:
        self.log_box.appendPlainText(step)
        self.progress.setValue(value)

    def handle_ingest_complete(self, count: int) -> None:
        self.progress.setValue(100)
        self.log_box.appendPlainText(f"✅ База обновлена. Добавлено {count} записей.")


__all__ = ["CreateBaseTab"]
