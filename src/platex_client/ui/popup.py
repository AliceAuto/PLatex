from __future__ import annotations

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..clipboard import copy_text_to_clipboard
from .glass_utils import POPUP_STYLESHEET, enable_acrylic_for_window


def _escape_html(text: str) -> str:
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


class Popup(QWidget):
    def __init__(self, title: str, message: str, latex: str) -> None:
        super().__init__(None)
        self._fade_timer: QTimer | None = None
        self._fade_step = 0
        self._fade_total_steps = 20
        self._latex = latex
        self._copied = False
        self._dwm_applied = False
        self.setObjectName("GlassPopup")
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setFixedSize(560, 180)
        self.setStyleSheet(POPUP_STYLESHEET)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        title_label = QLabel(_escape_html(title))
        title_label.setObjectName("PopupTitle")
        body_label = QLabel(_escape_html(message))
        body_label.setObjectName("PopupBody")
        body_label.setWordWrap(True)

        layout.addWidget(title_label)
        layout.addWidget(body_label)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._dwm_applied:
            self._dwm_applied = True
            hwnd = int(self.winId())
            if hwnd:
                enable_acrylic_for_window(hwnd, tint_color=0xE01E1E2E)

    def mousePressEvent(self, event):
        if not self._copied:
            try:
                copy_text_to_clipboard(self._latex)
            except Exception:
                pass
            self._copied = True
        self.close()
        event.accept()

    def keyPressEvent(self, event):
        self.close()
        event.accept()

    def start_auto_fade(self, timeout_ms: int) -> None:
        hold_ms = max(500, timeout_ms - 600)
        QTimer.singleShot(hold_ms, self._begin_fade)

    def _begin_fade(self) -> None:
        if not self.isVisible():
            return
        self._fade_step = 0
        self._fade_timer = QTimer(self)
        self._fade_timer.timeout.connect(self._fade_tick)
        self._fade_timer.start(25)

    def _fade_tick(self) -> None:
        if not self.isVisible():
            if self._fade_timer is not None:
                self._fade_timer.stop()
            return
        self._fade_step += 1
        progress = self._fade_step / self._fade_total_steps
        opacity = max(0.0, 1.0 - progress * progress)
        self.setWindowOpacity(opacity)
        if self._fade_step >= self._fade_total_steps:
            if self._fade_timer is not None:
                self._fade_timer.stop()
            self.close()
