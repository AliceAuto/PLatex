from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from platex_client.script_base import ScriptBase
from platex_client.hotkey_listener import simulate_click

logger = logging.getLogger("platex.scripts.hotkey_click")


class HotkeyClickScript(ScriptBase):
    """Script that simulates mouse clicks at predefined positions via global hotkeys.

    Supports configuration groups, each bound to a specific window title.
    When a hotkey is triggered, the script checks the foreground window title
    and executes the entry from the matching group. The default group (empty
    window field) works globally in any window.
    """

    def __init__(self) -> None:
        self._groups: list[dict[str, Any]] = [
            {"name": "\u9ed8\u8ba4", "window": "", "entries": []}
        ]

    @property
    def name(self) -> str:
        return "hotkey_click"

    @property
    def display_name(self) -> str:
        return "\u5feb\u6377\u952e\u70b9\u51fb"

    @property
    def description(self) -> str:
        return "\u901a\u8fc7\u5168\u5c40\u5feb\u6377\u952e\u77ac\u95f4\u79fb\u52a8\u9f20\u6807\u5230\u6307\u5b9a\u4f4d\u7f6e\u5e76\u70b9\u51fb\uff0c\u7136\u540e\u6062\u590d\u539f\u4f4d\u3002\u652f\u6301\u914d\u7f6e\u7ec4\u7ed1\u5b9a\u7a97\u53e3\uff0c\u9ed8\u8ba4\u7ec4\u5728\u4efb\u610f\u7a97\u53e3\u53ef\u7528\u3002"

    def get_hotkey_bindings(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for group in self._groups:
            for entry in group.get("entries", []):
                hotkey = self._normalize_hotkey_string(entry.get("hotkey", ""))
                if hotkey and hotkey not in result:
                    result[hotkey] = hotkey
        return result

    def on_hotkey(self, action: str) -> None:
        hotkey = action
        fg_title = self._get_foreground_window_title().lower()

        default_entries: list[dict[str, Any]] = []
        window_entries: list[dict[str, Any]] = []

        for group in self._groups:
            window = group.get("window", "")
            for entry in group.get("entries", []):
                entry_hotkey = self._normalize_hotkey_string(entry.get("hotkey", ""))
                if entry_hotkey != hotkey:
                    continue
                if window and window.lower() in fg_title:
                    window_entries.append(entry)
                elif not window:
                    default_entries.append(entry)

        entries_to_execute = window_entries if window_entries else default_entries
        for entry in entries_to_execute:
            x = int(entry.get("x", 0)) if isinstance(entry.get("x"), (int, float)) else 0
            y = int(entry.get("y", 0)) if isinstance(entry.get("y"), (int, float)) else 0
            button = entry.get("button", "left")
            logger.info(
                "Hotkey click: hotkey=%s pos=(%d,%d) button=%s fg_window=%s",
                hotkey, x, y, button, fg_title,
            )
            simulate_click(x, y, button)

    @staticmethod
    def _normalize_hotkey_string(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        normalized = value.split(",", 1)[0].strip()
        return normalized

    def _get_foreground_window_title(self) -> str:
        try:
            from platex_client.mouse_input import get_foreground_window_title
            return get_foreground_window_title()
        except ImportError:
            return ""

    def load_config(self, config: dict[str, Any]) -> None:
        if "groups" in config:
            raw_groups = config["groups"]
            if isinstance(raw_groups, list):
                self._groups = []
                for g in raw_groups:
                    if isinstance(g, dict):
                        group = {
                            "name": str(g.get("name", "")),
                            "window": str(g.get("window", "")),
                            "entries": [
                                dict(e) if isinstance(e, dict) else {}
                                for e in g.get("entries", [])
                            ],
                        }
                        self._groups.append(group)
            if not self._groups:
                self._groups = [{"name": "\u9ed8\u8ba4", "window": "", "entries": []}]
        else:
            raw_entries = config.get("entries", [])
            if not isinstance(raw_entries, list):
                raw_entries = []
            entries = [dict(e) if isinstance(e, dict) else {} for e in raw_entries]
            self._groups = [{"name": "\u9ed8\u8ba4", "window": "", "entries": entries}]

    def save_config(self) -> dict[str, Any]:
        return {"groups": self._groups}

    def set_groups(self, groups: list[dict[str, Any]]) -> None:
        self._groups = groups

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
                picked_x: int | None = None
                picked_y: int | None = None
                try:
                    import ctypes

                    class _POINT(ctypes.Structure):
                        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

                    pt = _POINT()
                    if ctypes.WinDLL("user32", use_last_error=True).GetCursorPos(ctypes.byref(pt)):
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
                    "QFrame { border: 1px solid rgba(100, 116, 148, 70); border-radius: 6px; background: #24253a; padding: 2px; }"
                    "QFrame QLabel { color: #b8c0dc; background: transparent; }"
                    "QSpinBox { padding: 2px 6px; border: 1px solid rgba(100, 116, 148, 70); border-radius: 3px; background: #282940; color: #b8c0dc; }"
                    "QSpinBox::up-button, QSpinBox::down-button { background: #282940; border: none; width: 16px; }"
                    "QComboBox { padding: 2px 8px; border: 1px solid rgba(100, 116, 148, 70); border-radius: 3px; background: #282940; color: #b8c0dc; }"
                    "QComboBox QAbstractItemView { background: #1c1c2e; color: #b8c0dc; border: 1px solid rgba(100, 116, 148, 70); selection-background-color: rgba(100, 140, 200, 80); }"
                    "QKeySequenceEdit { padding: 2px 8px; border: 1px solid rgba(100, 116, 148, 70); border-radius: 3px; background: #282940; color: #b8c0dc; }"
                )

                outer = QVBoxLayout(self)
                outer.setContentsMargins(10, 8, 10, 8)
                outer.setSpacing(6)

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
                    "QPushButton { color: #d4787e; font-weight: bold; border: 1px solid rgba(100, 116, 148, 70); border-radius: 4px; background: #282940; }"
                    "QPushButton:hover { background: #32334c; }"
                )
                btn_remove.clicked.connect(lambda: self.removed.emit(self))
                row1.addWidget(btn_remove)

                outer.addLayout(row1)

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
                    "QPushButton { padding: 4px 12px; border: 1px solid rgba(100, 140, 200, 100); border-radius: 4px; background: #282940; color: #7ba2d4; }"
                    "QPushButton:hover { background: #32334c; }"
                )
                btn_pick.clicked.connect(self._pick_position)
                row2.addWidget(btn_pick)

                row2.addStretch()
                outer.addLayout(row2)

                row3 = QHBoxLayout()
                row3.setSpacing(8)

                remark_label = QLabel("\u5907\u6ce8:")
                remark_label.setFixedWidth(40)
                row3.addWidget(remark_label)

                self._remark_edit = QLineEdit()
                self._remark_edit.setPlaceholderText("\u4e3a\u6b64\u5feb\u6377\u952e\u6dfb\u52a0\u5907\u6ce8\uff0c\u65b9\u4fbf\u8bc6\u522b")
                self._remark_edit.setText(str(entry.get("remark", "")))
                self._remark_edit.setStyleSheet(
                    "QLineEdit { padding: 4px 8px; border: 1px solid rgba(100, 116, 148, 70); border-radius: 4px; background: #282940; color: #b8c0dc; }"
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
                    settings_widget._schedule_settings_changed()

            def _on_value_changed(self) -> None:
                self.entry["x"] = self._x_spin.value()
                self.entry["y"] = self._y_spin.value()
                self.entry["button"] = self._button_combo.currentData()
                self.entry["remark"] = self._remark_edit.text()
                if settings_widget is not None:
                    settings_widget._schedule_settings_changed()

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
                    settings_widget._schedule_settings_changed()

        class _SettingsWidget(QWidget):
            def __init__(self, inner_parent: QWidget | None = None) -> None:
                super().__init__(inner_parent)
                self._entry_widgets: list[_HotkeyEntryWidget] = []
                self._settings_changed_callback: Callable[[], None] | None = None
                self._syncing = False
                self._current_group_index = 0
                self._pending_timer = QTimer(self)
                self._pending_timer.setSingleShot(True)
                self._pending_timer.setInterval(300)
                self._pending_timer.timeout.connect(self._emit_settings_changed)
                self._pick_countdown = 0
                self._pick_timer: QTimer | None = None

                main_layout = QVBoxLayout(self)
                main_layout.setContentsMargins(12, 12, 12, 12)
                main_layout.setSpacing(8)

                header = QLabel(
                    "\u5feb\u6377\u952e\u70b9\u51fb\u811a\u672c\u8bbe\u7f6e\n"
                    "\u89e6\u53d1\u5feb\u6377\u952e\u540e\uff0c\u9f20\u6807\u77ac\u95f4\u79fb\u52a8\u5230\u76ee\u6807\u4f4d\u7f6e\u5e76\u70b9\u51fb\uff0c\u7136\u540e\u6062\u590d\u539f\u4f4d\u3002\n"
                    "\u53ef\u521b\u5efa\u591a\u4e2a\u914d\u7f6e\u7ec4\uff0c\u6bcf\u4e2a\u914d\u7f6e\u7ec4\u7ed1\u5b9a\u6307\u5b9a\u7a97\u53e3\uff0c\u9ed8\u8ba4\u914d\u7f6e\u7ec4\u5728\u4efb\u610f\u7a97\u53e3\u53ef\u7528\u3002"
                )
                header.setStyleSheet("font-size: 13px; color: #8a90a8; margin-bottom: 8px;")
                header.setWordWrap(True)
                main_layout.addWidget(header)

                group_row = QHBoxLayout()
                group_row.setSpacing(8)

                group_row.addWidget(QLabel("\u914d\u7f6e\u7ec4:"))
                self._group_combo = QComboBox()
                self._group_combo.setMinimumWidth(120)
                self._group_combo.setStyleSheet(
                    "QComboBox { padding: 4px 8px; border: 1px solid rgba(100, 116, 148, 70); border-radius: 4px; background: #282940; color: #b8c0dc; }"
                    "QComboBox QAbstractItemView { background: #1c1c2e; color: #b8c0dc; border: 1px solid rgba(100, 116, 148, 70); selection-background-color: rgba(100, 140, 200, 80); }"
                )
                self._group_combo.currentIndexChanged.connect(self._on_group_changed)
                group_row.addWidget(self._group_combo, 1)

                btn_add_group = QPushButton("\u2795 \u6dfb\u52a0\u7ec4")
                btn_add_group.setStyleSheet(
                    "QPushButton { padding: 4px 10px; border: 1px solid rgba(100, 140, 200, 100); border-radius: 4px; background: #282940; color: #7ba2d4; }"
                    "QPushButton:hover { background: #32334c; }"
                )
                btn_add_group.clicked.connect(self._add_group)
                group_row.addWidget(btn_add_group)

                btn_remove_group = QPushButton("\u2715 \u5220\u9664\u7ec4")
                btn_remove_group.setStyleSheet(
                    "QPushButton { padding: 4px 10px; border: 1px solid rgba(100, 116, 148, 70); border-radius: 4px; background: #282940; color: #d4787e; }"
                    "QPushButton:hover { background: #32334c; }"
                )
                btn_remove_group.clicked.connect(self._remove_group)
                group_row.addWidget(btn_remove_group)

                main_layout.addLayout(group_row)

                window_row = QHBoxLayout()
                window_row.setSpacing(8)

                window_row.addWidget(QLabel("\u7a97\u53e3\u6807\u9898:"))
                self._window_edit = QLineEdit()
                self._window_edit.setPlaceholderText("\u7559\u7a7a\u8868\u793a\u5728\u4efb\u610f\u7a97\u53e3\u751f\u6548\uff08\u9ed8\u8ba4\u7ec4\uff09\uff0c\u586b\u5199\u7a97\u53e3\u6807\u9898\u5173\u952e\u8bcd\u7ed1\u5b9a\u7279\u5b9a\u7a97\u53e3")
                self._window_edit.setStyleSheet(
                    "QLineEdit { padding: 4px 8px; border: 1px solid rgba(100, 116, 148, 70); border-radius: 4px; background: #282940; color: #b8c0dc; }"
                )
                self._window_edit.textChanged.connect(self._on_window_changed)
                window_row.addWidget(self._window_edit, 1)

                self._btn_pick_window = QPushButton("\uD83D\uDD0D \u62FE\u53d6\u7a97\u53e3")
                self._btn_pick_window.setToolTip("\u70b9\u51fb\u540e\u6709 3 \u79d2\u65f6\u95f4\u5207\u6362\u5230\u76ee\u6807\u7a97\u53e3\uff0c\u81ea\u52a8\u83b7\u53d6\u7a97\u53e3\u6807\u9898")
                self._btn_pick_window.setMinimumWidth(100)
                self._btn_pick_window.setStyleSheet(
                    "QPushButton { padding: 4px 12px; border: 1px solid rgba(100, 140, 200, 100); border-radius: 4px; background: #282940; color: #7ba2d4; }"
                    "QPushButton:hover { background: #32334c; }"
                )
                self._btn_pick_window.clicked.connect(self._pick_window)
                window_row.addWidget(self._btn_pick_window)

                main_layout.addLayout(window_row)

                scroll = QScrollArea()
                scroll.setWidgetResizable(True)
                scroll.setFrameShape(QFrame.Shape.NoFrame)
                scroll.setStyleSheet(
                    "QScrollArea { background: transparent; border: none; }"
                    "QScrollBar:vertical { background: #1c1c2e; width: 8px; border-radius: 4px; }"
                    "QScrollBar::handle:vertical { background: rgba(90, 95, 120, 140); min-height: 30px; border-radius: 4px; }"
                    "QScrollBar::handle:vertical:hover { background: rgba(100, 140, 200, 140); }"
                    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
                )
                self._scroll_content = QWidget()
                self._scroll_content.setStyleSheet("background: transparent;")
                self._scroll_layout = QVBoxLayout(self._scroll_content)
                self._scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
                self._scroll_layout.setSpacing(8)
                scroll.setWidget(self._scroll_content)
                main_layout.addWidget(scroll)

                btn_add = QPushButton("\u2795 \u6dfb\u52a0\u5feb\u6377\u952e")
                btn_add.setStyleSheet(
                    "QPushButton { padding: 8px 16px; font-size: 13px; border: 1px solid rgba(100, 140, 200, 100); border-radius: 4px; background: #282940; color: #7ba2d4; }"
                    "QPushButton:hover { background: #32334c; }"
                )
                btn_add.clicked.connect(self._add_entry)
                main_layout.addWidget(btn_add)

                self._rebuild_group_combo()
                self._load_group_entries()

            def _rebuild_group_combo(self) -> None:
                self._group_combo.blockSignals(True)
                current = self._current_group_index
                self._group_combo.clear()
                for group in script_ref._groups:
                    name = group.get("name", "")
                    window = group.get("window", "")
                    if window:
                        label = f"{name} ({window})"
                    else:
                        label = name
                    self._group_combo.addItem(label)
                if 0 <= current < self._group_combo.count():
                    self._group_combo.setCurrentIndex(current)
                elif self._group_combo.count() > 0:
                    self._group_combo.setCurrentIndex(0)
                self._current_group_index = self._group_combo.currentIndex()
                self._group_combo.blockSignals(False)

            def _load_group_entries(self) -> None:
                for widget in list(self._entry_widgets):
                    self._scroll_layout.removeWidget(widget)
                    widget.setParent(None)
                    widget.deleteLater()
                self._entry_widgets.clear()

                self._syncing = True
                try:
                    idx = self._current_group_index
                    if 0 <= idx < len(script_ref._groups):
                        group = script_ref._groups[idx]
                        self._window_edit.setText(group.get("window", ""))
                        for entry_data in group.get("entries", []):
                            self._add_entry_with_data(entry_data)
                finally:
                    self._syncing = False

            def _save_current_group(self) -> None:
                idx = self._current_group_index
                if idx < 0 or idx >= len(script_ref._groups):
                    return
                group = script_ref._groups[idx]
                group["entries"] = [w.to_entry() for w in self._entry_widgets]
                group["window"] = self._window_edit.text()

            def _on_group_changed(self, index: int) -> None:
                if index < 0:
                    return
                self._save_current_group()
                self._current_group_index = index
                self._load_group_entries()
                self._rebuild_group_combo()

            def _on_window_changed(self, text: str) -> None:
                if self._syncing:
                    return
                idx = self._current_group_index
                if 0 <= idx < len(script_ref._groups):
                    script_ref._groups[idx]["window"] = text
                    self._rebuild_group_combo()
                    self._schedule_settings_changed()

            def _add_group(self) -> None:
                self._save_current_group()
                n = len(script_ref._groups) + 1
                new_group: dict[str, Any] = {
                    "name": f"\u914d\u7f6e\u7ec4 {n}",
                    "window": "",
                    "entries": [],
                }
                script_ref._groups.append(new_group)
                self._current_group_index = len(script_ref._groups) - 1
                self._rebuild_group_combo()
                self._load_group_entries()
                self._schedule_settings_changed()

            def _remove_group(self) -> None:
                if len(script_ref._groups) <= 1:
                    return
                idx = self._current_group_index
                if idx < 0 or idx >= len(script_ref._groups):
                    return
                script_ref._groups.pop(idx)
                if self._current_group_index >= len(script_ref._groups):
                    self._current_group_index = len(script_ref._groups) - 1
                self._rebuild_group_combo()
                self._load_group_entries()
                self._schedule_settings_changed()

            def _pick_window(self) -> None:
                self._pick_countdown = 3
                self._btn_pick_window.setEnabled(False)
                self._btn_pick_window.setText("3...")
                if self._pick_timer is not None:
                    self._pick_timer.stop()
                self._pick_timer = QTimer(self)
                self._pick_timer.setInterval(1000)
                self._pick_timer.timeout.connect(self._on_pick_tick)
                self._pick_timer.start()

            def _on_pick_tick(self) -> None:
                self._pick_countdown -= 1
                if self._pick_countdown <= 0:
                    if self._pick_timer is not None:
                        self._pick_timer.stop()
                        self._pick_timer = None
                    title = script_ref._get_foreground_window_title()
                    self._window_edit.setText(title)
                    self._btn_pick_window.setEnabled(True)
                    self._btn_pick_window.setText("\uD83D\uDD0D \u62FE\u53d6\u7a97\u53e3")
                else:
                    self._btn_pick_window.setText(f"{self._pick_countdown}...")

            def load_settings(self) -> None:
                self._syncing = True
                try:
                    self._current_group_index = 0
                    self._rebuild_group_combo()
                    self._load_group_entries()
                finally:
                    self._syncing = False

            def set_settings_changed_callback(self, callback: Callable[[], None] | None) -> None:
                self._settings_changed_callback = callback

            def _schedule_settings_changed(self) -> None:
                if self._syncing:
                    return
                self._pending_timer.start()

            def _emit_settings_changed(self) -> None:
                if self._syncing:
                    return
                self._save_current_group()
                if self._settings_changed_callback is not None:
                    self._settings_changed_callback()

            def _add_entry(self) -> None:
                default_entry = {"hotkey": "", "x": 0, "y": 0, "button": "left", "remark": ""}
                self._add_entry_with_data(default_entry)
                self._schedule_settings_changed()

            def _add_entry_with_data(self, entry_data: dict[str, Any]) -> None:
                entry_widget = _HotkeyEntryWidget(entry_data)
                entry_widget.removed.connect(self._remove_entry)
                self._entry_widgets.append(entry_widget)
                self._scroll_layout.addWidget(entry_widget)

            def _remove_entry(self, widget: _HotkeyEntryWidget, notify: bool = True) -> None:
                if widget in self._entry_widgets:
                    self._entry_widgets.remove(widget)
                self._scroll_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()
                if notify:
                    self._schedule_settings_changed()

            def save_settings(self) -> None:
                self._save_current_group()

        settings_widget = _SettingsWidget(parent)
        return settings_widget


def create_script() -> ScriptBase:
    return HotkeyClickScript()
