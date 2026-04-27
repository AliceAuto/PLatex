from __future__ import annotations

import ctypes
import logging
import sys

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


def enable_acrylic_for_window(hwnd: int, tint_color: int = 0x99000000) -> bool:
    if sys.platform != "win32":
        return False

    if _is_win11_22h2_or_later():
        return _enable_win11_backdrop(hwnd)
    if _is_win10_1803_or_later():
        return _enable_win10_acrylic(hwnd, tint_color)

    logger.debug("Windows version too old for acrylic effect, skipping")
    return False


def _enable_win11_backdrop(hwnd: int) -> bool:
    try:
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20

        _dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(ctypes.c_int(1)),
            ctypes.sizeof(ctypes.c_int),
        )

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


GLASS_STYLESHEET = """
QWidget#GlassRoot {
    background: #1c1c2e;
}

QTabWidget::pane {
    border: 1px solid rgba(100, 116, 148, 70);
    border-radius: 6px;
    background: #1c1c2e;
    top: -1px;
}

QTabWidget::tab-bar {
    alignment: left;
}

QTabBar::tab {
    background: #282940;
    color: #b8c0dc;
    padding: 7px 18px;
    margin-right: 1px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid rgba(100, 116, 148, 40);
    border-bottom: none;
    font-size: 13px;
}

QTabBar::tab:selected {
    background: #2e2f48;
    color: #7ba2d4;
    border: 1px solid rgba(100, 116, 148, 80);
    border-bottom: none;
    font-weight: 600;
}

QTabBar::tab:hover:!selected {
    background: #32334c;
    color: #94a8d0;
}

QPushButton {
    background: #282940;
    color: #b8c0dc;
    border: 1px solid rgba(100, 116, 148, 70);
    border-radius: 5px;
    padding: 5px 14px;
    font-size: 13px;
}

QPushButton:hover {
    background: #32334c;
    border-color: rgba(100, 116, 148, 120);
    color: #94a8d0;
}

QPushButton:pressed {
    background: #1e1f36;
    border-color: rgba(100, 116, 148, 140);
    color: #94a8d0;
}

QPushButton:disabled {
    background: #222236;
    color: #5a5e78;
    border-color: #333448;
}

QCheckBox {
    color: #b8c0dc;
    font-size: 13px;
    spacing: 8px;
}

QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 3px;
    border: 1px solid rgba(100, 116, 148, 100);
    background: #282940;
}

QCheckBox::indicator:checked {
    background: rgba(100, 140, 200, 160);
    border-color: rgba(100, 140, 200, 180);
}

QCheckBox::indicator:hover {
    border-color: rgba(120, 155, 210, 160);
}

QLabel {
    color: #b8c0dc;
    font-size: 13px;
}

QComboBox {
    background: #282940;
    color: #b8c0dc;
    border: 1px solid rgba(100, 116, 148, 70);
    border-radius: 5px;
    padding: 4px 10px;
    font-size: 13px;
    min-width: 100px;
}

QComboBox:hover {
    border-color: rgba(100, 116, 148, 120);
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid rgba(120, 155, 210, 160);
    margin-right: 6px;
}

QComboBox QAbstractItemView {
    background: #1c1c2e;
    color: #b8c0dc;
    border: 1px solid rgba(100, 116, 148, 70);
    border-radius: 5px;
    selection-background-color: rgba(100, 140, 200, 80);
    selection-color: #d0d6e8;
    outline: none;
    padding: 4px;
}

QLineEdit {
    background: #282940;
    color: #b8c0dc;
    border: 1px solid rgba(100, 116, 148, 70);
    border-radius: 5px;
    padding: 4px 10px;
    font-size: 13px;
}

QLineEdit:hover {
    border-color: rgba(100, 116, 148, 120);
}

QLineEdit:focus {
    border-color: rgba(100, 140, 200, 150);
}

QLineEdit:read-only {
    background: #1c1c2e;
    color: #8a90a8;
}

QPlainTextEdit {
    background: #14141e;
    color: #b8c0dc;
    border: 1px solid rgba(100, 116, 148, 50);
    border-radius: 5px;
    padding: 8px;
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    selection-background-color: rgba(100, 140, 200, 70);
    selection-color: #d0d6e8;
}

QScrollBar:vertical {
    background: #1c1c2e;
    width: 8px;
    margin: 0;
    border-radius: 4px;
}

QScrollBar::handle:vertical {
    background: rgba(90, 95, 120, 140);
    min-height: 30px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: rgba(100, 140, 200, 140);
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: #1c1c2e;
    height: 8px;
    margin: 0;
    border-radius: 4px;
}

QScrollBar::handle:horizontal {
    background: rgba(90, 95, 120, 140);
    min-width: 30px;
    border-radius: 4px;
}

QScrollBar::handle:horizontal:hover {
    background: rgba(100, 140, 200, 140);
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QMessageBox {
    background: #1c1c2e;
    color: #b8c0dc;
}

QMessageBox QLabel {
    color: #b8c0dc;
}

QMessageBox QPushButton {
    background: #282940;
    color: #b8c0dc;
    border: 1px solid rgba(100, 116, 148, 70);
    border-radius: 5px;
    padding: 5px 18px;
    min-width: 80px;
}

QMessageBox QPushButton:hover {
    background: #32334c;
    border-color: rgba(100, 116, 148, 120);
}
"""

POPUP_STYLESHEET = """
QWidget#GlassPopup {
    background: rgba(28, 28, 46, 255);
    border: 1px solid rgba(100, 140, 200, 100);
    border-radius: 10px;
}

QLabel#PopupTitle {
    font-size: 14px;
    font-weight: 600;
    color: #7ba2d4;
}

QLabel#PopupBody {
    font-size: 13px;
    color: #b8c0dc;
}
"""

HOTKEY_STATUS_STYLESHEET = """
QWidget#HotkeyStatusBox {
    background: #24253a;
    border: 1px solid rgba(100, 116, 148, 50);
    border-radius: 6px;
}

QWidget#HotkeyStatusBox QLabel {
    color: #b8c0dc;
}

QLabel#HotkeyStatusTitle {
    font-size: 13px;
    font-weight: 600;
    color: #7ba2d4;
}

QLabel#HotkeyStatusLabel {
    font-size: 12px;
    color: #a0a6be;
}
"""

LOG_VIEWER_STYLESHEET = """
QPlainTextEdit {
    font-family: 'Consolas', 'Courier New', monospace;
    font-size: 12px;
    background: #12121c;
    color: #94c498;
    border: 1px solid rgba(100, 116, 148, 40);
    border-radius: 5px;
    padding: 8px;
    selection-background-color: rgba(100, 140, 200, 70);
    selection-color: #d0d6e8;
}
"""
