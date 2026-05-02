from __future__ import annotations

import ctypes
import logging
import math
import sys

from PyQt6.QtCore import (
    QPropertyAnimation,
    QPoint,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QConicalGradient, QPainter, QPen, QRadialGradient
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
        self._theme_blend = 0.0

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

        self._theme_btn = ThemeToggleButton(self)
        self._theme_btn.setToolTip("")
        layout.addWidget(self._theme_btn)

    @property
    def theme_button(self) -> ThemeToggleButton:
        return self._theme_btn

    def set_theme_blend(self, blend: float) -> None:
        self._theme_blend = blend
        self.update()

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
        fill = _lerp_color((30, 30, 48, 35), (235, 238, 248, 180), self._theme_blend)
        painter.fillRect(self.rect(), QColor(fill))
        line = _lerp_color((255, 255, 255, 20), (0, 0, 0, 25), self._theme_blend)
        pen = QPen(QColor(line), 1)
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


class ThemeToggleButton(QWidget):
    theme_toggled = pyqtSignal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ThemeToggleButton")
        self.setFixedSize(36, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._is_light = False
        self._anim_progress = 0.0
        self._animating = False
        self._target_is_light = False
        self._hover = False
        self._animation: QPropertyAnimation | None = None

    def is_light_theme(self) -> bool:
        return self._is_light

    def set_light_theme(self, light: bool, animate: bool = True) -> None:
        if light == self._is_light and not self._animating:
            return
        if animate:
            self._target_is_light = light
            self._animating = True
            self._animation = QPropertyAnimation(self, b"anim_progress")
            self._animation.setDuration(700)
            self._animation.setStartValue(0.0)
            self._animation.setEndValue(1.0)
            self._animation.finished.connect(self._on_anim_finished)
            self._animation.start()
        else:
            self._is_light = light
            self._anim_progress = 0.0
            self.update()

    def _on_anim_finished(self) -> None:
        self._is_light = self._target_is_light
        self._animating = False
        self._anim_progress = 0.0
        self._animation = None
        self.update()

    @pyqtProperty(float)
    def anim_progress(self) -> float:
        return self._anim_progress

    @anim_progress.setter
    def anim_progress(self, value: float) -> None:
        self._anim_progress = value
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            new_light = not self._is_light if not self._animating else not self._target_is_light
            self.set_light_theme(new_light, animate=True)
            self.theme_toggled.emit(new_light)
        event.accept()

    def enterEvent(self, event) -> None:
        self._hover = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hover = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2

        if self._animating:
            self._paint_transition(painter, cx, cy, w, h)
        elif self._is_light:
            self._paint_sun(painter, cx, cy, 1.0)
        else:
            self._paint_moon(painter, cx, cy, 1.0)

        painter.end()

    def _paint_transition(self, painter: QPainter, cx: float, cy: float, w: float, h: float) -> None:
        p = self._anim_progress
        if p < 0.5:
            phase = p / 0.5
            opacity = 1.0 - phase
            offset_y = phase * h * 0.6
            if self._is_light:
                self._paint_sun(painter, cx, cy + offset_y, opacity)
            else:
                self._paint_moon(painter, cx, cy + offset_y, opacity)
        else:
            phase = (p - 0.5) / 0.5
            opacity = phase
            offset_y = (1.0 - phase) * h * 0.6
            if self._target_is_light:
                self._paint_sun(painter, cx, cy + offset_y, opacity)
            else:
                self._paint_moon(painter, cx, cy + offset_y, opacity)

    def _paint_sun(self, painter: QPainter, cx: float, cy: float, opacity: float) -> None:
        alpha = int(255 * min(1.0, opacity) * (1.0 if not self._hover else 1.0))
        radius = 6

        glow = QRadialGradient(cx, cy, radius * 2.5)
        glow.setColorAt(0, QColor(255, 200, 60, int(alpha * 0.3)))
        glow.setColorAt(1, QColor(255, 200, 60, 0))
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - radius * 2.5), int(cy - radius * 2.5), int(radius * 5), int(radius * 5))

        body_grad = QRadialGradient(cx - 1, cy - 1, radius)
        body_grad.setColorAt(0, QColor(255, 220, 80, alpha))
        body_grad.setColorAt(1, QColor(255, 180, 40, alpha))
        painter.setBrush(body_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - radius), int(cy - radius), radius * 2, radius * 2)

        ray_len = 3.5
        ray_inner = radius + 2
        num_rays = 8
        for i in range(num_rays):
            angle = i * (360 / num_rays)
            rad = math.radians(angle)
            x1 = cx + ray_inner * math.cos(rad)
            y1 = cy + ray_inner * math.sin(rad)
            x2 = cx + (ray_inner + ray_len) * math.cos(rad)
            y2 = cy + (ray_inner + ray_len) * math.sin(rad)
            pen = QPen(QColor(255, 200, 60, alpha), 1.5)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(int(x1), int(y1), int(x2), int(y2))

    def _paint_moon(self, painter: QPainter, cx: float, cy: float, opacity: float) -> None:
        alpha = int(255 * min(1.0, opacity) * (1.0 if not self._hover else 1.0))
        radius = 7

        glow = QRadialGradient(cx, cy, radius * 2.5)
        glow.setColorAt(0, QColor(180, 200, 255, int(alpha * 0.2)))
        glow.setColorAt(1, QColor(180, 200, 255, 0))
        painter.setBrush(glow)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - radius * 2.5), int(cy - radius * 2.5), int(radius * 5), int(radius * 5))

        body_grad = QRadialGradient(cx - 1, cy - 1, radius)
        body_grad.setColorAt(0, QColor(230, 240, 255, alpha))
        body_grad.setColorAt(1, QColor(190, 210, 245, alpha))
        painter.setBrush(body_grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cx - radius), int(cy - radius), radius * 2, radius * 2)

        cut_cx = cx + radius * 0.55
        cut_cy = cy - radius * 0.35
        cut_radius = radius * 0.8
        bg = self.parent()
        if bg is not None:
            bg_color = bg.palette().window().color()
            erase_color = QColor(bg_color.red(), bg_color.green(), bg_color.blue(), alpha)
        else:
            erase_color = QColor(30, 30, 48, alpha)
        painter.setBrush(erase_color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(int(cut_cx - cut_radius), int(cut_cy - cut_radius), int(cut_radius * 2), int(cut_radius * 2))

        star_positions = [(cx - 7, cy - 5), (cx + 5, cy + 6), (cx - 3, cy + 7)]
        for sx, sy in star_positions:
            star_alpha = int(alpha * 0.6)
            painter.setBrush(QColor(200, 220, 255, star_alpha))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(int(sx - 1), int(sy - 1), 2, 2)


def _lerp_color(dark: tuple[int, ...], light: tuple[int, ...], t: float) -> str:
    t = max(0.0, min(1.0, t))
    r = int(dark[0] + (light[0] - dark[0]) * t)
    g = int(dark[1] + (light[1] - dark[1]) * t)
    b = int(dark[2] + (light[2] - dark[2]) * t)
    a = int(dark[3] + (light[3] - dark[3]) * t)
    return f"rgba({r}, {g}, {b}, {a})"


_THEME_TOKENS: dict[str, tuple[tuple[int, ...], tuple[int, ...]]] = {
    "bg_content": ((30, 30, 48, 35), (235, 238, 248, 220)),
    "bg_titlebar_fill": ((30, 30, 48, 35), (235, 238, 248, 180)),
    "border_titlebar_line": ((255, 255, 255, 20), (0, 0, 0, 25)),
    "text_title": ((210, 218, 240, 230), (30, 35, 60, 230)),
    "bg_segment": ((50, 52, 78, 80), (210, 215, 232, 150)),
    "text_segment": ((180, 190, 215, 200), (60, 65, 90, 200)),
    "bg_segment_checked": ((80, 85, 120, 160), (170, 178, 210, 180)),
    "text_segment_checked": ((235, 240, 255, 240), (30, 35, 65, 240)),
    "bg_segment_hover": ((60, 62, 90, 100), (195, 200, 220, 120)),
    "text_segment_hover": ((200, 210, 230, 220), (50, 55, 80, 220)),
    "border_content": ((255, 255, 255, 18), (0, 0, 0, 25)),
    "bg_tab": ((50, 52, 78, 100), (215, 220, 238, 140)),
    "text_tab": ((180, 190, 215, 200), (60, 65, 90, 200)),
    "border_tab": ((255, 255, 255, 10), (0, 0, 0, 18)),
    "bg_tab_selected": ((60, 62, 92, 140), (175, 182, 215, 170)),
    "text_tab_selected": ((160, 200, 245, 255), (20, 60, 140, 255)),
    "border_tab_selected": ((140, 180, 230, 50), (30, 80, 160, 60)),
    "bg_tab_hover": ((58, 60, 88, 120), (200, 206, 228, 130)),
    "text_tab_hover": ((160, 175, 210, 230), (50, 60, 95, 230)),
    "bg_pane": ((30, 30, 48, 50), (225, 230, 245, 160)),
    "bg_btn": ((50, 52, 78, 120), (215, 220, 238, 180)),
    "text_btn": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "border_btn": ((255, 255, 255, 18), (0, 0, 0, 22)),
    "bg_btn_hover": ((65, 68, 100, 160), (195, 202, 225, 210)),
    "border_btn_hover": ((140, 180, 230, 70), (30, 80, 160, 70)),
    "text_btn_hover": ((210, 220, 240, 250), (35, 45, 75, 250)),
    "bg_btn_pressed": ((35, 37, 58, 160), (180, 188, 215, 210)),
    "border_btn_pressed": ((140, 180, 230, 90), (30, 80, 160, 90)),
    "text_btn_pressed": ((170, 180, 210, 230), (40, 50, 80, 230)),
    "bg_btn_disabled": ((40, 42, 62, 80), (200, 205, 220, 80)),
    "text_btn_disabled": ((90, 95, 120, 140), (140, 145, 165, 140)),
    "border_btn_disabled": ((255, 255, 255, 6), (0, 0, 0, 8)),
    "bg_primary": ((0, 122, 255, 150), (0, 100, 220, 180)),
    "text_primary_btn": ((255, 255, 255, 240), (255, 255, 255, 240)),
    "border_primary": ((0, 122, 255, 100), (0, 100, 220, 120)),
    "bg_primary_hover": ((20, 140, 255, 190), (10, 120, 240, 210)),
    "border_primary_hover": ((20, 140, 255, 140), (10, 120, 240, 160)),
    "bg_primary_pressed": ((0, 100, 220, 190), (0, 85, 200, 210)),
    "bg_danger": ((255, 69, 58, 130), (220, 50, 40, 150)),
    "text_danger": ((255, 255, 255, 230), (255, 255, 255, 230)),
    "border_danger": ((255, 69, 58, 80), (220, 50, 40, 100)),
    "bg_danger_hover": ((255, 55, 45, 180), (200, 40, 30, 190)),
    "border_danger_hover": ((255, 55, 45, 130), (200, 40, 30, 140)),
    "bg_danger_pressed": ((220, 50, 40, 180), (180, 35, 25, 190)),
    "text_yaml": ((140, 180, 230, 200), (30, 80, 160, 200)),
    "text_yaml_hover": ((170, 200, 240, 240), (20, 65, 140, 240)),
    "text_yaml_checked": ((120, 165, 225, 240), (15, 55, 130, 240)),
    "text_checkbox": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "border_checkbox": ((140, 180, 230, 70), (30, 80, 160, 70)),
    "bg_checkbox": ((50, 52, 78, 100), (215, 220, 238, 160)),
    "bg_checkbox_checked": ((0, 122, 255, 170), (0, 100, 220, 190)),
    "border_checkbox_checked": ((0, 122, 255, 150), (0, 100, 220, 170)),
    "border_checkbox_hover": ((140, 180, 230, 120), (30, 80, 160, 120)),
    "text_label": ((190, 200, 225, 230), (50, 55, 80, 230)),
    "text_section": ((140, 180, 230, 240), (30, 80, 160, 240)),
    "bg_combo": ((50, 52, 78, 120), (215, 220, 238, 180)),
    "text_combo": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "border_combo": ((255, 255, 255, 18), (0, 0, 0, 22)),
    "border_combo_hover": ((140, 180, 230, 70), (30, 80, 160, 70)),
    "arrow_combo": ((140, 180, 230, 150), (30, 80, 160, 150)),
    "bg_combo_dropdown": ((30, 30, 48, 220), (240, 242, 250, 240)),
    "text_combo_dropdown": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "border_combo_dropdown": ((140, 180, 230, 35), (0, 0, 0, 30)),
    "bg_combo_selected": ((0, 122, 255, 70), (0, 100, 220, 50)),
    "text_combo_selected": ((220, 230, 250, 240), (255, 255, 255, 240)),
    "bg_lineedit": ((50, 52, 78, 120), (215, 220, 238, 180)),
    "text_lineedit": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "border_lineedit": ((255, 255, 255, 18), (0, 0, 0, 22)),
    "border_lineedit_hover": ((140, 180, 230, 70), (30, 80, 160, 70)),
    "border_lineedit_focus": ((0, 122, 255, 140), (0, 100, 220, 160)),
    "bg_lineedit_ro": ((30, 30, 48, 100), (230, 232, 242, 120)),
    "text_lineedit_ro": ((140, 150, 175, 170), (120, 125, 145, 170)),
    "bg_plaintext": ((20, 20, 34, 140), (225, 230, 245, 180)),
    "text_plaintext": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "border_plaintext": ((255, 255, 255, 10), (0, 0, 0, 15)),
    "bg_plaintext_sel": ((0, 122, 255, 50), (0, 100, 220, 50)),
    "text_plaintext_sel": ((220, 230, 250, 240), (255, 255, 255, 240)),
    "scrollbar_handle": ((100, 110, 140, 80), (140, 148, 170, 80)),
    "scrollbar_handle_hover": ((0, 122, 255, 120), (0, 100, 220, 120)),
    "bg_msgbox": ((30, 30, 48, 230), (240, 242, 250, 240)),
    "text_msgbox": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "bg_msgbox_btn": ((50, 52, 78, 150), (215, 220, 238, 200)),
    "text_msgbox_btn": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "border_msgbox_btn": ((255, 255, 255, 18), (0, 0, 0, 22)),
    "bg_msgbox_btn_hover": ((65, 68, 100, 190), (195, 202, 225, 230)),
    "border_msgbox_btn_hover": ((140, 180, 230, 70), (30, 80, 160, 70)),
    "bg_tooltip": ((30, 30, 48, 220), (245, 247, 252, 240)),
    "text_tooltip": ((180, 190, 215, 230), (50, 55, 80, 230)),
    "border_tooltip": ((140, 180, 230, 45), (0, 0, 0, 30)),
    "text_groupbox": ((140, 180, 230, 190), (30, 80, 160, 190)),
    "border_groupbox": ((255, 255, 255, 12), (0, 0, 0, 18)),
    "slider_groove": ((255, 255, 255, 20), (0, 0, 0, 30)),
    "slider_handle": ((0, 122, 255, 170), (0, 100, 220, 190)),
    "slider_handle_hover": ((20, 140, 255, 220), (10, 120, 240, 230)),
    "bg_hotkey_box": ((40, 42, 64, 80), (220, 225, 240, 140)),
    "border_hotkey_box": ((255, 255, 255, 12), (0, 0, 0, 18)),
    "text_hotkey_box": ((190, 200, 225, 230), (50, 55, 80, 230)),
    "text_hotkey_title": ((140, 180, 230, 210), (30, 80, 160, 210)),
    "text_hotkey_label": ((160, 170, 195, 190), (80, 85, 110, 190)),
    "bg_popup": ((30, 30, 48, 35), (235, 238, 248, 220)),
    "border_popup": ((140, 180, 230, 50), (30, 80, 160, 60)),
    "text_popup_title": ((140, 180, 230, 240), (30, 80, 160, 240)),
    "text_popup_body": ((190, 200, 225, 230), (50, 55, 80, 230)),
    "bg_log": ((18, 18, 30, 140), (230, 235, 248, 180)),
    "text_log": ((148, 196, 152, 220), (40, 120, 50, 220)),
    "border_log": ((255, 255, 255, 8), (0, 0, 0, 12)),
    "bg_plugin_list": ((25, 25, 40, 120), (225, 228, 240, 180)),
    "border_plugin_list": ((255, 255, 255, 10), (0, 0, 0, 15)),
    "text_plugin_header": ((140, 180, 230, 220), (30, 80, 160, 220)),
    "bg_plugin_item_selected": ((0, 122, 255, 50), (0, 100, 220, 50)),
    "bg_plugin_item_hover": ((60, 62, 90, 60), (200, 206, 228, 80)),
    "border_plugin_item": ((255, 255, 255, 6), (0, 0, 0, 8)),
    "text_plugin_item_name": ((210, 220, 240, 230), (35, 40, 65, 230)),
    "text_plugin_item_desc": ((140, 150, 175, 190), (100, 105, 130, 190)),
    "text_plugin_detail_name": ((140, 180, 230, 240), (30, 80, 160, 240)),
    "text_plugin_detail_desc": ((160, 170, 195, 200), (80, 85, 110, 200)),
    "bg_plugin_separator": ((255, 255, 255, 12), (0, 0, 0, 15)),
    "text_plugin_empty": ((100, 110, 140, 160), (150, 155, 175, 160)),
    "bg_plugin_splitter": ((255, 255, 255, 10), (0, 0, 0, 12)),
}


def build_glass_stylesheet(blend: float = 0.0) -> str:
    c = {k: _lerp_color(v[0], v[1], blend) for k, v in _THEME_TOKENS.items()}
    return f"""
QWidget#GlassRoot {{
    background: transparent;
}}

QWidget#GlassContent {{
    background: {c['bg_content']};
    border: 1px solid {c['border_content']};
    border-radius: 10px;
}}

QWidget#MacTitleBar {{
    background: transparent;
}}

QLabel#TitleBarTitle {{
    color: {c['text_title']};
    font-size: 13px;
    font-weight: 500;
    padding-left: 4px;
}}

QPushButton#MacCloseBtn, QPushButton#MacMinimizeBtn, QPushButton#MacMaximizeBtn {{
    border: none;
    border-radius: 7px;
    padding: 0px;
    min-width: 14px;
    max-width: 14px;
    min-height: 14px;
    max-height: 14px;
}}

QPushButton#MacCloseBtn {{
    background: rgba(255, 95, 87, 210);
}}
QPushButton#MacCloseBtn:hover {{
    background: rgba(255, 60, 48, 250);
}}

QPushButton#MacMinimizeBtn {{
    background: rgba(255, 189, 46, 210);
}}
QPushButton#MacMinimizeBtn:hover {{
    background: rgba(245, 166, 35, 250);
}}

QPushButton#MacMaximizeBtn {{
    background: rgba(40, 201, 60, 210);
}}
QPushButton#MacMaximizeBtn:hover {{
    background: rgba(29, 185, 84, 250);
}}

QWidget#SegmentedTabBar {{
    background: {c['bg_segment']};
    border-radius: 8px;
    padding: 2px;
}}

QPushButton#SegmentedTabButton {{
    background: transparent;
    color: {c['text_segment']};
    border: none;
    border-radius: 6px;
    padding: 6px 20px;
    font-size: 13px;
    font-weight: 400;
}}

QPushButton#SegmentedTabButton:checked {{
    background: {c['bg_segment_checked']};
    color: {c['text_segment_checked']};
    font-weight: 600;
}}

QPushButton#SegmentedTabButton:hover:!checked {{
    background: {c['bg_segment_hover']};
    color: {c['text_segment_hover']};
}}

QTabWidget::pane {{
    border: 1px solid {c['border_content']};
    border-radius: 8px;
    background: {c['bg_pane']};
    top: -1px;
}}

QTabWidget::tab-bar {{
    alignment: left;
}}

QTabBar::tab {{
    background: {c['bg_tab']};
    color: {c['text_tab']};
    padding: 8px 22px;
    margin-right: 2px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    border: 1px solid {c['border_tab']};
    border-bottom: none;
    font-size: 13px;
    font-weight: 400;
}}

QTabBar::tab:selected {{
    background: {c['bg_tab_selected']};
    color: {c['text_tab_selected']};
    border: 1px solid {c['border_tab_selected']};
    border-bottom: none;
    font-weight: 600;
}}

QTabBar::tab:hover:!selected {{
    background: {c['bg_tab_hover']};
    color: {c['text_tab_hover']};
}}

QPushButton {{
    background: {c['bg_btn']};
    color: {c['text_btn']};
    border: 1px solid {c['border_btn']};
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
    font-weight: 400;
}}

QPushButton:hover {{
    background: {c['bg_btn_hover']};
    border-color: {c['border_btn_hover']};
    color: {c['text_btn_hover']};
}}

QPushButton:pressed {{
    background: {c['bg_btn_pressed']};
    border-color: {c['border_btn_pressed']};
    color: {c['text_btn_pressed']};
}}

QPushButton:disabled {{
    background: {c['bg_btn_disabled']};
    color: {c['text_btn_disabled']};
    border-color: {c['border_btn_disabled']};
}}

QPushButton#PrimaryAction {{
    background: {c['bg_primary']};
    color: {c['text_primary_btn']};
    border: 1px solid {c['border_primary']};
    font-weight: 500;
}}

QPushButton#PrimaryAction:hover {{
    background: {c['bg_primary_hover']};
    border-color: {c['border_primary_hover']};
}}

QPushButton#PrimaryAction:pressed {{
    background: {c['bg_primary_pressed']};
}}

QPushButton#DangerAction {{
    background: {c['bg_danger']};
    color: {c['text_danger']};
    border: 1px solid {c['border_danger']};
    font-weight: 500;
}}

QPushButton#DangerAction:hover {{
    background: {c['bg_danger_hover']};
    border-color: {c['border_danger_hover']};
}}

QPushButton#DangerAction:pressed {{
    background: {c['bg_danger_pressed']};
}}

QPushButton#YamlToggleBtn {{
    background: transparent;
    color: {c['text_yaml']};
    border: none;
    text-align: left;
    padding: 4px 0;
    font-size: 12px;
}}

QPushButton#YamlToggleBtn:hover {{
    color: {c['text_yaml_hover']};
}}

QPushButton#YamlToggleBtn:checked {{
    color: {c['text_yaml_checked']};
}}

QCheckBox {{
    color: {c['text_checkbox']};
    font-size: 13px;
    spacing: 8px;
}}

QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 5px;
    border: 1.5px solid {c['border_checkbox']};
    background: {c['bg_checkbox']};
}}

QCheckBox::indicator:checked {{
    background: {c['bg_checkbox_checked']};
    border-color: {c['border_checkbox_checked']};
}}

QCheckBox::indicator:hover {{
    border-color: {c['border_checkbox_hover']};
}}

QLabel {{
    color: {c['text_label']};
    font-size: 13px;
}}

QLabel#SectionTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {c['text_section']};
}}

QComboBox {{
    background: {c['bg_combo']};
    color: {c['text_combo']};
    border: 1px solid {c['border_combo']};
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 13px;
    min-width: 100px;
}}

QComboBox:hover {{
    border-color: {c['border_combo_hover']};
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {c['arrow_combo']};
    margin-right: 6px;
}}

QComboBox QAbstractItemView {{
    background: {c['bg_combo_dropdown']};
    color: {c['text_combo_dropdown']};
    border: 1px solid {c['border_combo_dropdown']};
    border-radius: 6px;
    selection-background-color: {c['bg_combo_selected']};
    selection-color: {c['text_combo_selected']};
    outline: none;
    padding: 4px;
}}

QLineEdit {{
    background: {c['bg_lineedit']};
    color: {c['text_lineedit']};
    border: 1px solid {c['border_lineedit']};
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 13px;
}}

QLineEdit:hover {{
    border-color: {c['border_lineedit_hover']};
}}

QLineEdit:focus {{
    border-color: {c['border_lineedit_focus']};
}}

QLineEdit:read-only {{
    background: {c['bg_lineedit_ro']};
    color: {c['text_lineedit_ro']};
}}

QPlainTextEdit {{
    background: {c['bg_plaintext']};
    color: {c['text_plaintext']};
    border: 1px solid {c['border_plaintext']};
    border-radius: 6px;
    padding: 8px;
    font-family: 'Consolas', 'SF Mono', 'Courier New', monospace;
    font-size: 12px;
    selection-background-color: {c['bg_plaintext_sel']};
    selection-color: {c['text_plaintext_sel']};
}}

QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 4px 2px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical {{
    background: {c['scrollbar_handle']};
    min-height: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:vertical:hover {{
    background: {c['scrollbar_handle_hover']};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px 4px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal {{
    background: {c['scrollbar_handle']};
    min-width: 30px;
    border-radius: 4px;
}}

QScrollBar::handle:horizontal:hover {{
    background: {c['scrollbar_handle_hover']};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QScrollBar::add-page:horizontal, QScrollBar::add-page:horizontal {{
    background: none;
}}

QMessageBox {{
    background: {c['bg_msgbox']};
    color: {c['text_msgbox']};
}}

QMessageBox QLabel {{
    color: {c['text_msgbox']};
}}

QMessageBox QPushButton {{
    background: {c['bg_msgbox_btn']};
    color: {c['text_msgbox_btn']};
    border: 1px solid {c['border_msgbox_btn']};
    border-radius: 6px;
    padding: 6px 20px;
    min-width: 80px;
}}

QMessageBox QPushButton:hover {{
    background: {c['bg_msgbox_btn_hover']};
    border-color: {c['border_msgbox_btn_hover']};
}}

QToolTip {{
    background: {c['bg_tooltip']};
    color: {c['text_tooltip']};
    border: 1px solid {c['border_tooltip']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}}

QGroupBox {{
    color: {c['text_groupbox']};
    border: 1px solid {c['border_groupbox']};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: 500;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

QSlider::groove:horizontal {{
    height: 4px;
    background: {c['slider_groove']};
    border-radius: 2px;
}}

QSlider::handle:horizontal {{
    background: {c['slider_handle']};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}}

QSlider::handle:horizontal:hover {{
    background: {c['slider_handle_hover']};
}}

QWidget#PluginListPanel {{
    background: {c['bg_plugin_list']};
    border-right: 1px solid {c['border_plugin_list']};
}}

QLabel#PluginListHeader {{
    color: {c['text_plugin_header']};
    font-size: 13px;
    font-weight: 600;
    padding: 10px 8px 6px 8px;
    border: none;
}}

QListWidget#PluginList {{
    background: transparent;
    border: none;
    outline: none;
    padding: 0px;
}}

QListWidget#PluginList::item {{
    background: transparent;
    border-bottom: 1px solid {c['border_plugin_item']};
    padding: 0px;
    margin: 0px;
}}

QListWidget#PluginList::item:selected {{
    background: {c['bg_plugin_item_selected']};
}}

QListWidget#PluginList::item:hover:!selected {{
    background: {c['bg_plugin_item_hover']};
}}

QWidget#PluginListItem {{
    background: transparent;
}}

QLabel#PluginItemName {{
    color: {c['text_plugin_item_name']};
    font-size: 13px;
    font-weight: 500;
}}

QLabel#PluginItemDesc {{
    color: {c['text_plugin_item_desc']};
    font-size: 11px;
}}

QWidget#PluginDetailPanel {{
    background: transparent;
}}

QLabel#PluginDetailName {{
    color: {c['text_plugin_detail_name']};
    font-size: 16px;
    font-weight: 600;
}}

QLabel#PluginDetailDesc {{
    color: {c['text_plugin_detail_desc']};
    font-size: 12px;
}}

QWidget#PluginDetailSeparator {{
    background: {c['bg_plugin_separator']};
}}

QLabel#PluginEmptyState {{
    color: {c['text_plugin_empty']};
    font-size: 14px;
}}

QSplitter#PluginSplitter::handle {{
    background: {c['bg_plugin_splitter']};
}}
"""


def build_popup_stylesheet(blend: float = 0.0) -> str:
    c = {k: _lerp_color(v[0], v[1], blend) for k, v in _THEME_TOKENS.items()}
    return f"""
QWidget#GlassPopup {{
    background: {c['bg_popup']};
    border: 1px solid {c['border_popup']};
    border-radius: 12px;
}}

QLabel#PopupTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {c['text_popup_title']};
}}

QLabel#PopupBody {{
    font-size: 13px;
    color: {c['text_popup_body']};
}}
"""


def build_hotkey_status_stylesheet(blend: float = 0.0) -> str:
    c = {k: _lerp_color(v[0], v[1], blend) for k, v in _THEME_TOKENS.items()}
    return f"""
QWidget#HotkeyStatusBox {{
    background: {c['bg_hotkey_box']};
    border: 1px solid {c['border_hotkey_box']};
    border-radius: 8px;
}}

QWidget#HotkeyStatusBox QLabel {{
    color: {c['text_hotkey_box']};
}}

QLabel#HotkeyStatusTitle {{
    font-size: 13px;
    font-weight: 600;
    color: {c['text_hotkey_title']};
}}

QLabel#HotkeyStatusLabel {{
    font-size: 12px;
    color: {c['text_hotkey_label']};
}}
"""


def build_log_viewer_stylesheet(blend: float = 0.0) -> str:
    c = {k: _lerp_color(v[0], v[1], blend) for k, v in _THEME_TOKENS.items()}
    return f"""
QPlainTextEdit {{
    font-family: 'Consolas', 'SF Mono', 'Courier New', monospace;
    font-size: 12px;
    background: {c['bg_log']};
    color: {c['text_log']};
    border: 1px solid {c['border_log']};
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {c['bg_plaintext_sel']};
    selection-color: {c['text_plaintext_sel']};
}}
"""


GLASS_STYLESHEET = build_glass_stylesheet(0.0)

POPUP_STYLESHEET = build_popup_stylesheet(0.0)

HOTKEY_STATUS_STYLESHEET = build_hotkey_status_stylesheet(0.0)

LOG_VIEWER_STYLESHEET = build_log_viewer_stylesheet(0.0)
