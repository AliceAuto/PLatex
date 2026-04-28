from __future__ import annotations

import ctypes
import logging
import sys

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

logger = logging.getLogger("platex.ui.glass_utils")

if sys.platform == "win32":
    _dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _get_windows_build() -> int:
    if sys.platform != "win32":
        return 0
    try:
        class OSVERSIONINFOEXW(ctypes.Structure):
            _fields_ = [
                ("dwOSVersionInfoSize", ctypes.c_ulong),
                ("dwMajorVersion", ctypes.c_ulong),
                ("dwMinorVersion", ctypes.c_ulong),
                ("dwBuildNumber", ctypes.c_ulong),
                ("dwPlatformId", ctypes.c_ulong),
                ("szCSDVersion", ctypes.c_wchar * 128),
            ]

        ver = OSVERSIONINFOEXW()
        ver.dwOSVersionInfoSize = ctypes.sizeof(OSVERSIONINFOEXW)

        try:
            ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
            ntdll.RtlGetVersion(ctypes.byref(ver))
            return ver.dwBuildNumber
        except Exception:
            _kernel32.GetVersionExW(ctypes.byref(ver))
            return ver.dwBuildNumber
    except Exception:
        return 0


def _is_win11_22h2_or_later() -> bool:
    return _get_windows_build() >= 22621


def _is_win10_1803_or_later() -> bool:
    return _get_windows_build() >= 17134


def _is_remote_session() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(_user32.GetSystemMetrics(0x1000))
    except Exception:
        return False


def enable_acrylic_for_window(hwnd: int, tint_color: int = 0x99000000) -> bool:
    if sys.platform != "win32":
        return False

    if _is_remote_session():
        logger.debug("Remote desktop session detected, skipping acrylic effect")
        return False

    if _is_win11_22h2_or_later():
        return _enable_win11_backdrop(hwnd)
    if _is_win10_1803_or_later():
        return _enable_win10_acrylic(hwnd, tint_color)

    logger.debug("Windows version too old for acrylic effect, skipping")
    return False


def _enable_win11_backdrop(hwnd: int) -> bool:
    if not hwnd or not _user32.IsWindow(hwnd):
        return False
    try:
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_WINDOW_CORNER_PREFERENCE = 33

        _dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(ctypes.c_int(1)),
            ctypes.sizeof(ctypes.c_int),
        )

        try:
            _dwmapi.DwmSetWindowAttribute(
                hwnd,
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(ctypes.c_int(2)),
                ctypes.sizeof(ctypes.c_int),
            )
        except Exception:
            pass

        backdrop_type = ctypes.c_int(3)
        hr = _dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(backdrop_type),
            ctypes.sizeof(backdrop_type),
        )
        if hr == 0:
            logger.debug("Win11 DWMWA_SYSTEMBACKDROP_TYPE=Acrylic applied")
            return True
        logger.warning("DwmSetWindowAttribute SYSTEMBACKDROP_TYPE failed: hr=%s", hr)
    except Exception as exc:
        logger.exception("Win11 backdrop failed: %s", exc)
    return False


def _enable_win10_acrylic(hwnd: int, tint_color: int = 0x99000000) -> bool:
    if not hwnd or not _user32.IsWindow(hwnd):
        return False
    try:
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_uint),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_uint),
            ]

        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("Data", ctypes.POINTER(ACCENT_POLICY)),
                ("SizeOfData", ctypes.c_size_t),
            ]

        ACCENT_ENABLE_ACRYLICBLURBEHIND = 4
        WCA_ACCENT_POLICY = 19

        accent = ACCENT_POLICY()
        accent.AccentState = ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        accent.GradientColor = tint_color
        accent.AnimationId = 0

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = WCA_ACCENT_POLICY
        data.Data = ctypes.pointer(accent)
        data.SizeOfData = ctypes.sizeof(accent)

        _user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        logger.debug("Win10 Acrylic blur applied (tint=0x%08X)", tint_color)
        return True
    except Exception as exc:
        logger.exception("Win10 acrylic failed: %s", exc)
    return False


class MacTitleBar(QWidget):
    close_clicked = pyqtSignal()
    minimize_clicked = pyqtSignal()
    maximize_clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, title: str = "") -> None:
        super().__init__(parent)
        self.setObjectName("MacTitleBar")
        self.setFixedHeight(38)
        self._drag_pos: QPoint | None = None
        self._title = title

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(0)

        btn_container = QWidget()
        btn_container.setFixedWidth(56)
        btn_layout = QHBoxLayout(btn_container)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(8)

        self._btn_close = self._make_traffic_button("MacCloseBtn")
        self._btn_minimize = self._make_traffic_button("MacMinimizeBtn")
        self._btn_maximize = self._make_traffic_button("MacMaximizeBtn")

        self._btn_close.clicked.connect(self.close_clicked.emit)
        self._btn_minimize.clicked.connect(self.minimize_clicked.emit)
        self._btn_maximize.clicked.connect(self.maximize_clicked.emit)

        btn_layout.addWidget(self._btn_close)
        btn_layout.addWidget(self._btn_minimize)
        btn_layout.addWidget(self._btn_maximize)
        layout.addWidget(btn_container)

        self._title_label = QLabel(title)
        self._title_label.setObjectName("TitleBarTitle")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_label, 1)

        right_spacer = QWidget()
        right_spacer.setFixedWidth(56)
        layout.addWidget(right_spacer)

    def _make_traffic_button(self, obj_name: str) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName(obj_name)
        btn.setFixedSize(14, 14)
        btn.setCursor(Qt.CursorShape.ArrowCursor)
        return btn

    def set_title(self, title: str) -> None:
        self._title = title
        self._title_label.setText(title)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self.maximize_clicked.emit()
        event.accept()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(30, 30, 48, 35))
        pen = QPen(QColor(255, 255, 255, 20), 1)
        painter.setPen(pen)
        painter.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        painter.end()


class SegmentedTabBar(QWidget):
    currentChanged = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SegmentedTabBar")
        self._tabs: list[str] = []
        self._current_index = -1
        self._btn_group = QButtonGroup(self)
        self._btn_group.setExclusive(True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        self._buttons: list[QPushButton] = []
        self._btn_group.idClicked.connect(self._on_clicked)

    def addTab(self, text: str) -> int:
        idx = len(self._tabs)
        self._tabs.append(text)
        btn = QPushButton(text)
        btn.setObjectName("SegmentedTabButton")
        btn.setCheckable(True)
        self._btn_group.addButton(btn, idx)
        self._layout.addWidget(btn)
        self._buttons.append(btn)
        if self._current_index < 0:
            self._current_index = 0
            btn.setChecked(True)
        return idx

    def setTabText(self, index: int, text: str) -> None:
        if 0 <= index < len(self._buttons):
            self._buttons[index].setText(text)

    def currentIndex(self) -> int:
        return self._current_index

    def setCurrentIndex(self, index: int) -> None:
        if 0 <= index < len(self._buttons):
            self._current_index = index
            self._buttons[index].setChecked(True)

    def count(self) -> int:
        return len(self._tabs)

    def _on_clicked(self, idx: int) -> None:
        if idx != self._current_index:
            self._current_index = idx
            self.currentChanged.emit(idx)


GLASS_STYLESHEET = """
QWidget#GlassRoot {
    background: transparent;
}

QWidget#GlassContent {
    background: rgba(30, 30, 48, 35);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 10px;
}

QWidget#MacTitleBar {
    background: transparent;
}

QLabel#TitleBarTitle {
    color: rgba(210, 218, 240, 230);
    font-size: 13px;
    font-weight: 500;
    padding-left: 4px;
}

QPushButton#MacCloseBtn, QPushButton#MacMinimizeBtn, QPushButton#MacMaximizeBtn {
    border: none;
    border-radius: 7px;
    padding: 0px;
    min-width: 14px;
    max-width: 14px;
    min-height: 14px;
    max-height: 14px;
}

QPushButton#MacCloseBtn {
    background: rgba(255, 95, 87, 210);
}
QPushButton#MacCloseBtn:hover {
    background: rgba(255, 60, 48, 250);
}

QPushButton#MacMinimizeBtn {
    background: rgba(255, 189, 46, 210);
}
QPushButton#MacMinimizeBtn:hover {
    background: rgba(245, 166, 35, 250);
}

QPushButton#MacMaximizeBtn {
    background: rgba(40, 201, 60, 210);
}
QPushButton#MacMaximizeBtn:hover {
    background: rgba(29, 185, 84, 250);
}

QWidget#SegmentedTabBar {
    background: rgba(50, 52, 78, 80);
    border-radius: 8px;
    padding: 2px;
}

QPushButton#SegmentedTabButton {
    background: transparent;
    color: rgba(180, 190, 215, 200);
    border: none;
    border-radius: 6px;
    padding: 6px 20px;
    font-size: 13px;
    font-weight: 400;
}

QPushButton#SegmentedTabButton:checked {
    background: rgba(80, 85, 120, 160);
    color: rgba(235, 240, 255, 240);
    font-weight: 600;
}

QPushButton#SegmentedTabButton:hover:!checked {
    background: rgba(60, 62, 90, 100);
    color: rgba(200, 210, 230, 220);
}

QTabWidget::pane {
    border: 1px solid rgba(255, 255, 255, 15);
    border-radius: 8px;
    background: rgba(30, 30, 48, 50);
    top: -1px;
}

QTabWidget::tab-bar {
    alignment: left;
}

QTabBar::tab {
    background: rgba(50, 52, 78, 100);
    color: rgba(180, 190, 215, 200);
    padding: 8px 22px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border: 1px solid rgba(255, 255, 255, 10);
    border-bottom: none;
    font-size: 13px;
    font-weight: 400;
}

QTabBar::tab:selected {
    background: rgba(60, 62, 92, 140);
    color: rgba(160, 200, 245, 255);
    border: 1px solid rgba(140, 180, 230, 50);
    border-bottom: none;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background: rgba(58, 60, 88, 120);
    color: rgba(160, 175, 210, 230);
}

QPushButton {
    background: rgba(50, 52, 78, 120);
    color: rgba(180, 190, 215, 230);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 400;
}

QPushButton:hover {
    background: rgba(65, 68, 100, 160);
    border-color: rgba(140, 180, 230, 70);
    color: rgba(210, 220, 240, 250);
}

QPushButton:pressed {
    background: rgba(35, 37, 58, 160);
    border-color: rgba(140, 180, 230, 90);
    color: rgba(170, 180, 210, 230);
}

QPushButton:disabled {
    background: rgba(40, 42, 62, 80);
    color: rgba(90, 95, 120, 140);
    border-color: rgba(255, 255, 255, 6);
}

QPushButton#PrimaryAction {
    background: rgba(0, 122, 255, 150);
    color: rgba(255, 255, 255, 240);
    border: 1px solid rgba(0, 122, 255, 100);
    font-weight: 500;
}

QPushButton#PrimaryAction:hover {
    background: rgba(20, 140, 255, 190);
    border-color: rgba(20, 140, 255, 140);
}

QPushButton#PrimaryAction:pressed {
    background: rgba(0, 100, 220, 190);
}

QPushButton#DangerAction {
    background: rgba(255, 69, 58, 130);
    color: rgba(255, 255, 255, 230);
    border: 1px solid rgba(255, 69, 58, 80);
    font-weight: 500;
}

QPushButton#DangerAction:hover {
    background: rgba(255, 55, 45, 180);
    border-color: rgba(255, 55, 45, 130);
}

QPushButton#DangerAction:pressed {
    background: rgba(220, 50, 40, 180);
}

QPushButton#YamlToggleBtn {
    background: transparent;
    color: rgba(140, 180, 230, 200);
    border: none;
    text-align: left;
    padding: 4px 0;
    font-size: 12px;
}

QPushButton#YamlToggleBtn:hover {
    color: rgba(170, 200, 240, 240);
}

QPushButton#YamlToggleBtn:checked {
    color: rgba(120, 165, 225, 240);
}

QCheckBox {
    color: rgba(180, 190, 215, 230);
    font-size: 13px;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid rgba(140, 180, 230, 70);
    background: rgba(50, 52, 78, 100);
}

QCheckBox::indicator:checked {
    background: rgba(0, 122, 255, 170);
    border-color: rgba(0, 122, 255, 150);
}

QCheckBox::indicator:hover {
    border-color: rgba(140, 180, 230, 120);
}

QLabel {
    color: rgba(190, 200, 225, 230);
    font-size: 13px;
}

QLabel#SectionTitle {
    font-size: 14px;
    font-weight: 600;
    color: rgba(140, 180, 230, 240);
}

QComboBox {
    background: rgba(50, 52, 78, 120);
    color: rgba(180, 190, 215, 230);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 13px;
    min-width: 100px;
}

QComboBox:hover {
    border-color: rgba(140, 180, 230, 70);
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid rgba(140, 180, 230, 150);
    margin-right: 6px;
}

QComboBox QAbstractItemView {
    background: rgba(30, 30, 48, 220);
    color: rgba(180, 190, 215, 230);
    border: 1px solid rgba(140, 180, 230, 35);
    border-radius: 6px;
    selection-background-color: rgba(0, 122, 255, 70);
    selection-color: rgba(220, 230, 250, 240);
    outline: none;
    padding: 4px;
}

QLineEdit {
    background: rgba(50, 52, 78, 120);
    color: rgba(180, 190, 215, 230);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 13px;
}

QLineEdit:hover {
    border-color: rgba(140, 180, 230, 70);
}

QLineEdit:focus {
    border-color: rgba(0, 122, 255, 140);
}

QLineEdit:read-only {
    background: rgba(30, 30, 48, 100);
    color: rgba(140, 150, 175, 170);
}

QPlainTextEdit {
    background: rgba(20, 20, 34, 140);
    color: rgba(180, 190, 215, 230);
    border: 1px solid rgba(255, 255, 255, 10);
    border-radius: 6px;
    padding: 8px;
    font-family: 'Consolas', 'SF Mono', 'Courier New', monospace;
    font-size: 12px;
    selection-background-color: rgba(0, 122, 255, 50);
    selection-color: rgba(220, 230, 250, 240);
}

QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 4px 2px;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: rgba(100, 110, 140, 80);
    min-height: 30px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(0, 122, 255, 120);
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 2px 4px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background: rgba(100, 110, 140, 80);
    min-width: 30px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background: rgba(0, 122, 255, 120);
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QScrollBar::add-page:horizontal, QScrollBar::add-page:horizontal {
    background: none;
}

QMessageBox {
    background: rgba(30, 30, 48, 230);
    color: rgba(180, 190, 215, 230);
}

QMessageBox QLabel {
    color: rgba(180, 190, 215, 230);
}

QMessageBox QPushButton {
    background: rgba(50, 52, 78, 150);
    color: rgba(180, 190, 215, 230);
    border: 1px solid rgba(255, 255, 255, 18);
    border-radius: 6px;
    padding: 6px 20px;
    min-width: 80px;
}

QMessageBox QPushButton:hover {
    background: rgba(65, 68, 100, 190);
    border-color: rgba(140, 180, 230, 70);
}

QToolTip {
    background: rgba(30, 30, 48, 220);
    color: rgba(180, 190, 215, 230);
    border: 1px solid rgba(140, 180, 230, 45);
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

QGroupBox {
    color: rgba(140, 180, 230, 190);
    border: 1px solid rgba(255, 255, 255, 12);
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: 500;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}

QSlider::groove:horizontal {
    height: 4px;
    background: rgba(255, 255, 255, 20);
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background: rgba(0, 122, 255, 170);
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}

QSlider::handle:horizontal:hover {
    background: rgba(20, 140, 255, 220);
}
"""

POPUP_STYLESHEET = """
QWidget#GlassPopup {
    background: rgba(30, 30, 48, 35);
    border: 1px solid rgba(140, 180, 230, 50);
    border-radius: 12px;
}

QLabel#PopupTitle {
    font-size: 14px;
    font-weight: 600;
    color: rgba(140, 180, 230, 240);
}

QLabel#PopupBody {
    font-size: 13px;
    color: rgba(190, 200, 225, 230);
}
"""

HOTKEY_STATUS_STYLESHEET = """
QWidget#HotkeyStatusBox {
    background: rgba(40, 42, 64, 80);
    border: 1px solid rgba(255, 255, 255, 12);
    border-radius: 8px;
}

QWidget#HotkeyStatusBox QLabel {
    color: rgba(190, 200, 225, 230);
}

QLabel#HotkeyStatusTitle {
    font-size: 13px;
    font-weight: 600;
    color: rgba(140, 180, 230, 210);
}

QLabel#HotkeyStatusLabel {
    font-size: 12px;
    color: rgba(160, 170, 195, 190);
}
"""

LOG_VIEWER_STYLESHEET = """
QPlainTextEdit {
    font-family: 'Consolas', 'SF Mono', 'Courier New', monospace;
    font-size: 12px;
    background: rgba(18, 18, 30, 140);
    color: rgba(148, 196, 152, 220);
    border: 1px solid rgba(255, 255, 255, 8);
    border-radius: 6px;
    padding: 8px;
    selection-background-color: rgba(0, 122, 255, 50);
    selection-color: rgba(220, 230, 250, 240);
}
"""
