from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .glass_utils import LOG_VIEWER_STYLESHEET
from ..i18n import t, on_language_changed

logger = logging.getLogger("platex.ui.log_tab")


class LogTab(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self._log_refresh_btn = QPushButton(t("btn_refresh"))
        self._log_refresh_btn.setFixedWidth(70)
        self._log_auto_refresh = QCheckBox(t("log_auto_refresh"))
        self._log_line_limit = QComboBox()
        self._log_line_limit.addItems([t("line_50"), t("line_100"), t("line_200"), t("line_500")])
        self._log_line_limit.setCurrentIndex(1)
        self._log_line_limit.setFixedWidth(90)
        self._log_open_terminal_btn = QPushButton(t("log_open_terminal"))
        self._log_open_terminal_btn.setFixedWidth(80)
        self._label_display = QLabel(t("label_display"))
        toolbar.addWidget(self._log_refresh_btn)
        toolbar.addWidget(self._log_auto_refresh)
        toolbar.addWidget(self._label_display)
        toolbar.addWidget(self._log_line_limit)
        toolbar.addStretch()
        toolbar.addWidget(self._log_open_terminal_btn)
        layout.addLayout(toolbar)

        self._log_viewer = QPlainTextEdit()
        self._log_viewer.setReadOnly(True)
        self._log_viewer.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._log_viewer.setStyleSheet(LOG_VIEWER_STYLESHEET)
        layout.addWidget(self._log_viewer, 1)

        self._log_refresh_btn.clicked.connect(self._refresh_log)

        self._log_auto_timer = QTimer()
        self._log_auto_timer.setInterval(3000)
        self._log_auto_timer.timeout.connect(self._refresh_log)
        self._log_auto_refresh.toggled.connect(
            lambda checked: self._log_auto_timer.start() if checked else self._log_auto_timer.stop()
        )

        on_language_changed(self._on_language_changed)

    def _on_language_changed(self, language: str) -> None:
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._log_refresh_btn.setText(t("btn_refresh"))
        self._log_auto_refresh.setText(t("log_auto_refresh"))
        self._label_display.setText(t("label_display"))
        self._log_open_terminal_btn.setText(t("log_open_terminal"))

        current_index = self._log_line_limit.currentIndex()
        self._log_line_limit.blockSignals(True)
        self._log_line_limit.clear()
        self._log_line_limit.addItems([t("line_50"), t("line_100"), t("line_200"), t("line_500")])
        self._log_line_limit.setCurrentIndex(current_index if current_index >= 0 else 1)
        self._log_line_limit.blockSignals(False)

    def bind_controller(self, controller: object) -> None:
        self._controller = controller
        self._log_open_terminal_btn.clicked.connect(self._open_terminal)
        self._refresh_log()

    def _refresh_log(self) -> None:
        if self._controller is None:
            return

        try:
            payload: dict[str, Any] = {}
            try:
                general_tab = getattr(self._controller, '_general_tab', None)
                if general_tab is not None:
                    payload = general_tab.parse_yaml()
            except Exception:
                payload = {}
            log_val = payload.get("log_file")
            if isinstance(log_val, str) and log_val.strip():
                log_path = Path(log_val.strip())
            else:
                from ..config import default_log_path
                log_path = default_log_path()
        except Exception:
            log_path = None

        if log_path is None or not log_path.exists():
            self._log_viewer.setPlainText(t("log_file_not_found", path=log_path))
            return

        try:
            limit_map = {0: 50, 1: 100, 2: 200, 3: 500}
            limit = limit_map.get(self._log_line_limit.currentIndex(), 100)
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            content = "\n".join(lines[-limit:])
            self._log_viewer.setPlainText(content)
            self._log_viewer.moveCursor(QTextCursor.MoveOperation.End)
        except Exception as exc:
            self._log_viewer.setPlainText(t("log_read_error", error=exc))

    def _open_terminal(self) -> None:
        if self._controller is None:
            return
        from ..tray import _open_runtime_terminal

        payload: dict[str, Any] = {}
        try:
            general_tab = getattr(self._controller, '_general_tab', None)
            if general_tab is not None:
                payload = general_tab.parse_yaml()
        except Exception:
            payload = {}

        script_val = payload.get("script")
        log_val = payload.get("log_file")
        script_path = Path(script_val.strip()) if isinstance(script_val, str) and script_val.strip() else self._controller.app.script_path
        log_path = log_val.strip() if isinstance(log_val, str) else ""
        _open_runtime_terminal(script_path, log_path)
