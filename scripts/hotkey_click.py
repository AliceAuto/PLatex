from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from platex_client.script_base import ScriptBase
from platex_client.hotkey_listener import simulate_click

logger = logging.getLogger("platex.scripts.hotkey_click")


class HotkeyClickScript(ScriptBase):
    """Script that simulates mouse clicks at predefined positions via global hotkeys.

    When a hotkey is triggered, the mouse instantly moves to the target position,
    clicks, then returns to the original position.
    """

    def __init__(self) -> None:
        self._entries: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "hotkey_click"

    @property
    def display_name(self) -> str:
        return "\u5feb\u6377\u952e\u70b9\u51fb"

    @property
    def description(self) -> str:
        return "\u901a\u8fc7\u5168\u5c40\u5feb\u6377\u952e\u77ac\u95f4\u79fb\u52a8\u9f20\u6807\u5230\u6307\u5b9a\u4f4d\u7f6e\u5e76\u70b9\u51fb\uff0c\u7136\u540e\u6062\u590d\u539f\u4f4d"

    def get_hotkey_bindings(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for i, entry in enumerate(self._entries):
            hotkey = self._normalize_hotkey_string(entry.get("hotkey", ""))
            if hotkey:
                result[hotkey] = f"click_{i}"
        return result

    @staticmethod
    def _normalize_hotkey_string(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        # QKeySequenceEdit may emit multi-sequence text like
        # "Ctrl+Shift+E, Ctrl+Shift+E"; keep only the first one.
        normalized = value.split(",", 1)[0].strip()
        return normalized
    def on_hotkey(self, action: str) -> None:
        if not action.startswith("click_"):
            return
        try:
            idx = int(action.split("_", 1)[1])
        except (ValueError, IndexError):
            return
        if 0 <= idx < len(self._entries):
            entry = self._entries[idx]
            x = int(entry.get("x", 0)) if isinstance(entry.get("x"), (int, float)) else 0
            y = int(entry.get("y", 0)) if isinstance(entry.get("y"), (int, float)) else 0
            button = entry.get("button", "left")
            logger.info("Hotkey click: action=%s pos=(%d,%d) button=%s", action, x, y, button)
            simulate_click(x, y, button)

    def load_config(self, config: dict[str, Any]) -> None:
        raw_entries = config.get("entries", [])
        if not isinstance(raw_entries, list):
            logger.warning("hotkey_click entries must be a list, got %s", type(raw_entries).__name__)
            raw_entries = []
        self._entries = [dict(e) if isinstance(e, dict) else {} for e in raw_entries]

    def save_config(self) -> dict[str, Any]:
        return {"entries": [dict(e) for e in self._entries]}

    def set_entries(self, entries: list[dict[str, Any]]) -> None:
        """Update the entry list (called from settings UI)."""
        self._entries = entries

    def create_settings_widget(self, parent=None):
        try:
            from PyQt6.QtCore import Qt, QTimer, pyqtSignal
            from PyQt6.QtWidgets import (
                QWidget,
                QVBoxLayout,
                QHBoxLayout,
                QPushButton,
                QLabel,
                QSpinBox,
                QComboBox,
                QScrollArea,
                QFrame,
                QKeySequenceEdit,
                QLineEdit,
            )
            from PyQt6.QtGui import QKeySequence
        except ImportError:
            logger.warning("PyQt6 not available; hotkey_click settings UI disabled")
            return None

        script_ref = self
        settings_changed_callback: Callable[[], None] | None = None
        settings_widget: _SettingsWidget | None = None

        class _PositionPickerOverlay(QWidget):
            position_picked = pyqtSignal(int, int)

            def __init__(self) -> None:
                super().__init__()
                self.setWindowFlags(
                    Qt.WindowType.FramelessWindowHint
                    | Qt.WindowType.WindowStaysOnTopHint
                    | Qt.WindowType.Tool
                )
                self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
                self.setCursor(Qt.CursorShape.CrossCursor)
                self.setStyleSheet("background: transparent;")

                from PyQt6.QtGui import QScreen
                from PyQt6.QtWidgets import QApplication

                screens = QApplication.screens()
                if screens:
                    x1 = min(s.geometry().left() for s in screens)
                    y1 = min(s.geometry().top() for s in screens)
                    x2 = max(s.geometry().right() for s in screens)
                    y2 = max(s.geometry().bottom() for s in screens)
                else:
                    x1, y1, x2, y2 = 0, 0, 1920, 1080

                self._geo = (x1, y1, x2 - x1, y2 - y1)
                self.setGeometry(*self._geo)

                self._label = QLabel(
                    "\u70b9\u51fb\u5c4f\u5e55\u9009\u62e9\u4f4d\u7f6e\n\u6309 Esc \u53d6\u6d88",
                    self,
                )
                self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self._label.setStyleSheet(
                    "font-size: 28px; color: white; background: rgba(0,0,0,160);"
                    "border-radius: 16px; padding: 30px;"
                )
                self._label.adjustSize()
                cx = (x1 + x2) // 2 - self._label.width() // 2
                cy = (y1 + y2) // 2 - self._label.height() // 2
                self._label.move(cx, cy)

            def paintEvent(self, event) -> None:  # noqa: N802
                from PyQt6.QtGui import QPainter, QColor

                painter = QPainter(self)
                painter.fillRect(self.rect(), QColor(0, 0, 0, 60))
                painter.end()

            def mousePressEvent(self, event) -> None:  # noqa: N802
                # Use Win32 cursor coordinates when available so picked and click
                # coordinates share the same system across DPI/multi-monitor setups.
                picked_x: int | None = None
                picked_y: int | None = None
                try:
                    import ctypes

                    class _POINT(ctypes.Structure):
                        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                    pt = _POINT()
                    if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                        picked_x, picked_y = int(pt.x), int(pt.y)
                except Exception:
                    picked_x = None
                    picked_y = None

                if picked_x is None or picked_y is None:
                    pos = event.globalPosition()
                    picked_x, picked_y = int(pos.x()), int(pos.y())

                self.position_picked.emit(picked_x, picked_y)
                self.close()

            def keyPressEvent(self, event) -> None:  # noqa: N802
                if event.key() == Qt.Key.Key_Escape:
                    self.close()

        class _HotkeyEntryWidget(QFrame):
            removed = pyqtSignal(object)

            def __init__(self, entry: dict[str, Any], parent: QWidget | None = None) -> None:
                super().__init__(parent)
                self.entry = dict(entry)
                self.setFrameShape(QFrame.Shape.StyledPanel)
                self.setStyleSheet(
                    "QFrame { border: 1px solid #c8d0dc; border-radius: 8px; background: #fafbfc; padding: 2px; }"
                )

                outer = QVBoxLayout(self)
                outer.setContentsMargins(10, 8, 10, 8)
                outer.setSpacing(6)

                # Row 1: hotkey | button type | delete
                row1 = QHBoxLayout()
                row1.setSpacing(10)

                row1.addWidget(QLabel("\u5feb\u6377\u952e:"))
                self._hotkey_edit = QKeySequenceEdit()
                self._hotkey_edit.setMinimumWidth(140)
                existing = entry.get("hotkey", "")
                if existing:
                    seq = QKeySequence(existing)
                    self._hotkey_edit.setKeySequence(seq)
                self._hotkey_edit.keySequenceChanged.connect(self._on_hotkey_changed)
                row1.addWidget(self._hotkey_edit, 1)

                row1.addWidget(QLabel("\u9f20\u6807\u952e:"))
                self._button_combo = QComboBox()
                self._button_combo.addItem("\u5de6\u952e", "left")
                self._button_combo.addItem("\u53f3\u952e", "right")
                self._button_combo.setMinimumWidth(70)
                btn = entry.get("button", "left")
                idx = self._button_combo.findData(btn)
                if idx >= 0:
                    self._button_combo.setCurrentIndex(idx)
                self._button_combo.currentIndexChanged.connect(self._on_value_changed)
                row1.addWidget(self._button_combo)

                btn_remove = QPushButton("\u2715")
                btn_remove.setFixedSize(28, 28)
                btn_remove.setToolTip("\u5220\u9664\u6b64\u5feb\u6377\u952e")
                btn_remove.setStyleSheet(
                    "QPushButton { color: #cc3333; font-weight: bold; border: 1px solid #ddd; border-radius: 4px; background: #fff; }"
                    "QPushButton:hover { background: #fee; }"
                )
                btn_remove.clicked.connect(lambda: self.removed.emit(self))
                row1.addWidget(btn_remove)

                outer.addLayout(row1)

                # Row 2: X Y spinboxes | pick position
                row2 = QHBoxLayout()
                row2.setSpacing(10)

                row2.addWidget(QLabel("X:"))
                self._x_spin = QSpinBox()
                self._x_spin.setRange(-32768, 32767)
                self._x_spin.setMinimumWidth(80)
                self._x_spin.setValue(int(entry.get("x", 0)))
                self._x_spin.valueChanged.connect(self._on_value_changed)
                row2.addWidget(self._x_spin)

                row2.addWidget(QLabel("Y:"))
                self._y_spin = QSpinBox()
                self._y_spin.setRange(-32768, 32767)
                self._y_spin.setMinimumWidth(80)
                self._y_spin.setValue(int(entry.get("y", 0)))
                self._y_spin.valueChanged.connect(self._on_value_changed)
                row2.addWidget(self._y_spin)

                row2.addSpacing(6)

                btn_pick = QPushButton("\uD83D\uDCCD \u62FE\u53d6\u5750\u6807")
                btn_pick.setToolTip("\u70b9\u51fb\u540e\u5728\u5c4f\u5e55\u4e0a\u70b9\u51fb\u9009\u62e9\u76ee\u6807\u4f4d\u7f6e")
                btn_pick.setMinimumWidth(100)
                btn_pick.setStyleSheet(
                    "QPushButton { padding: 4px 12px; border: 1px solid #7aa2ff; border-radius: 4px; background: #eef3ff; color: #3366cc; }"
                    "QPushButton:hover { background: #dbe5ff; }"
                )
                btn_pick.clicked.connect(self._pick_position)
                row2.addWidget(btn_pick)

                row2.addStretch()
                outer.addLayout(row2)

                # Row 3: remark
                row3 = QHBoxLayout()
                row3.setSpacing(8)

                remark_label = QLabel("\u5907\u6ce8:")
                remark_label.setFixedWidth(40)
                row3.addWidget(remark_label)

                self._remark_edit = QLineEdit()
                self._remark_edit.setPlaceholderText("\u4e3a\u6b64\u5feb\u6377\u952e\u6dfb\u52a0\u5907\u6ce8\uff0c\u65b9\u4fbf\u8bc6\u522b")
                self._remark_edit.setText(str(entry.get("remark", "")))
                self._remark_edit.setStyleSheet(
                    "QLineEdit { padding: 4px 8px; border: 1px solid #d0d0d0; border-radius: 4px; background: #fff; }"
                )
                self._remark_edit.textChanged.connect(self._on_value_changed)
                row3.addWidget(self._remark_edit, 1)

                outer.addLayout(row3)

                self._overlay: _PositionPickerOverlay | None = None

            def to_entry(self) -> dict[str, Any]:
                return {
                    "hotkey": self._hotkey_edit.keySequence().toString(),
                    "x": self._x_spin.value(),
                    "y": self._y_spin.value(),
                    "button": self._button_combo.currentData(),
                    "remark": self._remark_edit.text(),
                }

            def _on_hotkey_changed(self, seq: QKeySequence) -> None:
                self.entry["hotkey"] = script_ref._normalize_hotkey_string(seq.toString())
                if settings_widget is not None:
                    settings_widget._emit_settings_changed()

            def _on_value_changed(self) -> None:
                self.entry["x"] = self._x_spin.value()
                self.entry["y"] = self._y_spin.value()
                self.entry["button"] = self._button_combo.currentData()
                self.entry["remark"] = self._remark_edit.text()
                if settings_widget is not None:
                    settings_widget._emit_settings_changed()

            def _pick_position(self) -> None:
                self._overlay = _PositionPickerOverlay()
                self._overlay.position_picked.connect(self._set_position)
                self._overlay.show()

            def _set_position(self, x: int, y: int) -> None:
                self._x_spin.setValue(x)
                self._y_spin.setValue(y)
                self.entry["x"] = x
                self.entry["y"] = y
                if settings_widget is not None:
                    settings_widget._emit_settings_changed()

        class _SettingsWidget(QWidget):
            def __init__(self, inner_parent: QWidget | None = None) -> None:
                super().__init__(inner_parent)
                self._entries: list[_HotkeyEntryWidget] = []
                self._settings_changed_callback: Callable[[], None] | None = None
                self._syncing = False
                self._pending_timer = QTimer(self)
                self._pending_timer.setSingleShot(True)
                self._pending_timer.setInterval(300)
                self._pending_timer.timeout.connect(self._emit_settings_changed)

                main_layout = QVBoxLayout(self)
                main_layout.setContentsMargins(12, 12, 12, 12)
                main_layout.setSpacing(8)

                header = QLabel(
                    "\u5feb\u6377\u952e\u70b9\u51fb\u811a\u672c\u8bbe\u7f6e\n"
                    "\u89e6\u53d1\u5feb\u6377\u952e\u540e\uff0c\u9f20\u6807\u77ac\u95f4\u79fb\u52a8\u5230\u76ee\u6807\u4f4d\u7f6e\u5e76\u70b9\u51fb\uff0c\u7136\u540e\u6062\u590d\u539f\u4f4d\u3002"
                )
                header.setStyleSheet("font-size: 13px; color: #555; margin-bottom: 8px;")
                header.setWordWrap(True)
                main_layout.addWidget(header)

                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                self._scroll_content = QWidget()
                self._scroll_layout = QVBoxLayout(self._scroll_content)
                self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
                self._scroll_layout.setSpacing(8)
                scroll.setWidget(self._scroll_content)
                main_layout.addWidget(scroll)

                btn_add = QPushButton("\u2795 \u6dfb\u52a0\u5feb\u6377\u952e")
                btn_add.setStyleSheet("QPushButton { padding: 8px 16px; font-size: 13px; }")
                btn_add.clicked.connect(self._add_entry)
                main_layout.addWidget(btn_add)

                for entry_data in script_ref._entries:
                    self._add_entry_with_data(entry_data)

            def load_settings(self) -> None:
                # Rebuild widgets from script runtime state so YAML/UI stay in sync.
                self._syncing = True
                try:
                    for widget in list(self._entries):
                        self._remove_entry(widget, notify=False)
                    for entry_data in script_ref._entries:
                        self._add_entry_with_data(entry_data)
                finally:
                    self._syncing = False

            def set_settings_changed_callback(self, callback: Callable[[], None] | None) -> None:
                self._settings_changed_callback = callback

            def _schedule_settings_changed(self) -> None:
                if self._syncing:
                    return

            def _emit_settings_changed(self) -> None:
                if self._syncing:
                    return
                script_ref.set_entries([w.to_entry() for w in self._entries])
                if self._settings_changed_callback is not None:
                    self._settings_changed_callback()

            def _add_entry(self) -> None:
                default_entry = {"hotkey": "", "x": 0, "y": 0, "button": "left", "remark": ""}
                self._add_entry_with_data(default_entry)
                self._schedule_settings_changed()

            def _add_entry_with_data(self, entry_data: dict[str, Any]) -> None:
                entry_widget = _HotkeyEntryWidget(entry_data)
                entry_widget.removed.connect(self._remove_entry)
                self._entries.append(entry_widget)
                self._scroll_layout.addWidget(entry_widget)

            def _remove_entry(self, widget: _HotkeyEntryWidget, notify: bool = True) -> None:
                if widget in self._entries:
                    self._entries.remove(widget)
                self._scroll_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
                if notify:
                    self._schedule_settings_changed()

            def save_settings(self) -> None:
                entries = [w.to_entry() for w in self._entries]
                script_ref.set_entries(entries)

        settings_widget = _SettingsWidget(parent)
        return settings_widget


def create_script() -> ScriptBase:
    return HotkeyClickScript()