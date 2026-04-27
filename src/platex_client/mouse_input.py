from __future__ import annotations

import ctypes
import logging
import threading
import time

from .platform_utils import IS_WINDOWS, USER32

logger = logging.getLogger("platex.mouse_input")

_IS_WINDOWS = IS_WINDOWS
_USER32 = USER32

_PYNPUT_AVAILABLE = False
try:
    from pynput.mouse import Controller as _MouseController, Button as _MouseButton
    _PYNPUT_AVAILABLE = True
except ImportError:
    _MouseController = None
    _MouseButton = None


def get_foreground_window_title() -> str:
    """Return the title of the current foreground window.

    Uses Win32 GetForegroundWindow + GetWindowTextW on Windows.
    Returns an empty string if the API is unavailable or the window has no title.
    """
    if not _IS_WINDOWS or _USER32 is None:
        return ""
    try:
        hwnd = _USER32.GetForegroundWindow()
        if not hwnd:
            return ""
        length = _USER32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        _USER32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def _win32_simulate_click(x: int, y: int, button: str = "left") -> bool:
    if not _IS_WINDOWS or _USER32 is None:
        return False

    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    INPUT_MOUSE = 0

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("mouseData", ctypes.c_ulong),
            ("dwFlags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("ii", MOUSEINPUT)]

    screen_w = _USER32.GetSystemMetrics(0)
    screen_h = _USER32.GetSystemMetrics(1)
    if screen_w <= 0 or screen_h <= 0:
        return False

    block_released = False

    def _ensure_unblock() -> None:
        nonlocal block_released
        if not block_released:
            block_released = True
            try:
                _USER32.BlockInput(False)
            except Exception:
                pass

    _block_input_watchdog = threading.Timer(0.8, _ensure_unblock)
    _block_input_watchdog.daemon = True

    try:
        block_result = _USER32.BlockInput(True)
        if not block_result:
            logger.debug("BlockInput failed (requires elevated privileges), proceeding without input blocking")

        _block_input_watchdog.start()

        orig = ctypes.wintypes.POINT()
        _USER32.GetCursorPos(ctypes.byref(orig))
        orig_x, orig_y = orig.x, orig.y

        _USER32.SetCursorPos(x, y)
        time.sleep(0.005)

        if button == "left":
            down_flag, up_flag = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
        else:
            down_flag, up_flag = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP

        extra = ctypes.c_ulong(0)
        down = INPUT(type=INPUT_MOUSE, ii=MOUSEINPUT(
            dx=0, dy=0, mouseData=0,
            dwFlags=down_flag, time=0, dwExtraInfo=ctypes.pointer(extra),
        ))
        up = INPUT(type=INPUT_MOUSE, ii=MOUSEINPUT(
            dx=0, dy=0, mouseData=0,
            dwFlags=up_flag, time=0, dwExtraInfo=ctypes.pointer(extra),
        ))
        _USER32.SendInput(1, ctypes.byref(down), ctypes.sizeof(INPUT))
        _USER32.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))

        time.sleep(0.005)
        _USER32.SetCursorPos(orig_x, orig_y)

        return True
    except Exception:
        return False
    finally:
        _block_input_watchdog.cancel()
        _ensure_unblock()


def simulate_click(x: int, y: int, button: str = "left") -> None:
    """Simulate a mouse click at (x, y) then restore the cursor position.

    Uses Win32 SendInput on Windows for sub-5ms round-trip (fast path).
    Falls back to pynput on other platforms.
    """
    if not isinstance(x, int) or not isinstance(y, int):
        raise TypeError(f"Mouse coordinates must be integers, got x={type(x).__name__}, y={type(y).__name__}")
    if x < 0 or y < 0:
        logger.warning("Negative mouse coordinates (%d, %d) are unusual, clamping to 0", x, y)
        x = max(0, x)
        y = max(0, y)

    if button not in ("left", "right"):
        logger.warning("Invalid mouse button '%s', defaulting to 'left'", button)
        button = "left"

    if _IS_WINDOWS and _USER32 is not None:
        screen_w = _USER32.GetSystemMetrics(0)
        screen_h = _USER32.GetSystemMetrics(1)
        if screen_w > 0 and screen_h > 0:
            if x > screen_w or y > screen_h:
                raise ValueError(f"Click coordinates ({x}, {y}) exceed screen bounds ({screen_w}x{screen_h})")

    if _win32_simulate_click(x, y, button):
        logger.info("Simulated %s click at (%d, %d) via Win32 API", button, x, y)
        return

    if not _PYNPUT_AVAILABLE:
        logger.error("No click simulation method available; cannot simulate click")
        return

    try:
        mouse = _MouseController()
        original_pos = mouse.position
        btn = _MouseButton.left if button == "left" else _MouseButton.right
        try:
            mouse.position = (x, y)
            time.sleep(0.01)
            mouse.click(btn)
            time.sleep(0.005)
        finally:
            mouse.position = original_pos
        logger.info("Simulated %s click at (%d, %d) via pynput, restored to %s", button, x, y, original_pos)
    except Exception:
        logger.exception("Failed to simulate click at (%d, %d)", x, y)
