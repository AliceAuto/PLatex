from __future__ import annotations

import logging
import threading
import time
from typing import Callable

logger = logging.getLogger("platex.hotkeys")

_PYNPUT_AVAILABLE = False
try:
    from pynput import keyboard as _pynput_keyboard
    from pynput.mouse import Controller as _MouseController, Button as _MouseButton

    _PYNPUT_AVAILABLE = True
except ImportError:
    _pynput_keyboard = None  # type: ignore[assignment]
    _MouseController = None  # type: ignore[assignment]
    _MouseButton = None  # type: ignore[assignment]

_IS_WINDOWS = False
_USER32 = None
try:
    import ctypes

    _USER32 = ctypes.windll.user32
    _IS_WINDOWS = True
except (ImportError, OSError):
    pass


def convert_hotkey_str(hotkey: str) -> str:
    """Convert a human-friendly hotkey string to pynput GlobalHotKeys format.

    "Ctrl+Alt+1"  ->  "<ctrl>+<alt>+1"
    "Ctrl+Shift+F5" -> "<ctrl>+<shift>+<f5>"
    """
    if not hotkey or not hotkey.strip():
        raise ValueError(f"Invalid hotkey string: {hotkey!r}")

    modifiers = {
        "ctrl": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "win": "<cmd>",
        "cmd": "<cmd>",
        "super": "<cmd>",
    }
    special_keys = {
        "space": "<space>",
        "enter": "<enter>",
        "return": "<enter>",
        "tab": "<tab>",
        "escape": "<escape>",
        "esc": "<escape>",
        "backspace": "<backspace>",
        "delete": "<delete>",
        "insert": "<insert>",
        "home": "<home>",
        "end": "<end>",
        "page_up": "<page_up>",
        "page_down": "<page_down>",
        "up": "<up>",
        "down": "<down>",
        "left": "<left>",
        "right": "<right>",
        "caps_lock": "<caps_lock>",
    }

    parts = hotkey.split("+")
    if not parts:
        raise ValueError(f"Invalid hotkey string: {hotkey!r}")

    converted: list[str] = []
    for part in parts:
        key = part.strip().lower()
        if not key:
            raise ValueError(f"Empty key segment in hotkey string: {hotkey!r}")
        if key in modifiers:
            converted.append(modifiers[key])
        elif key in special_keys:
            converted.append(special_keys[key])
        elif key.startswith("f") and key[1:].isdigit():
            converted.append(f"<{key}>")
        elif len(key) == 1 and key.isalnum():
            converted.append(key)
        else:
            converted.append(f"<{key}>")
    return "+".join(converted)


def _win32_simulate_click(x: int, y: int, button: str = "left") -> bool:
    """Fast Win32 API click: move-click-restore in ~1ms using SendInput.

    Returns True if successful, False if the API is unavailable.
    """
    if not _IS_WINDOWS or _USER32 is None:
        return False

    MOUSEEVENTF_MOVE = 0x0001
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

    # Get screen dimensions for coordinate normalization
    screen_w = _USER32.GetSystemMetrics(0)  # SM_CXSCREEN
    screen_h = _USER32.GetSystemMetrics(1)  # SM_CYSCREEN
    if screen_w <= 0 or screen_h <= 0:
        return False

    try:
        # Save original cursor position
        orig = ctypes.wintypes.POINT()
        _USER32.GetCursorPos(ctypes.byref(orig))
        orig_x, orig_y = orig.x, orig.y

        # Move to target
        _USER32.SetCursorPos(x, y)

        # Small sleep to ensure position is set before click
        time.sleep(0.008)

        # Build click inputs
        if button == "left":
            down_flag = MOUSEEVENTF_LEFTDOWN
            up_flag = MOUSEEVENTF_LEFTUP
        else:
            down_flag = MOUSEEVENTF_RIGHTDOWN
            up_flag = MOUSEEVENTF_RIGHTUP

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

        # Small delay before restoring position
        time.sleep(0.005)

        # Restore original position
        _USER32.SetCursorPos(orig_x, orig_y)
        return True
    except Exception:
        return False


class HotkeyListener:
    """Global hotkey listener using pynput.

    Registers key combinations and dispatches callbacks when triggered.
    Supports dynamic registration and unregistration.
    """

    def __init__(self) -> None:
        self._bindings: dict[str, Callable[[], None]] = {}
        self._action_map: dict[str, str] = {}
        self._listener: object | None = None
        self._lock = threading.Lock()
        self._running = False
        self._suspended = threading.Event()
        self._suspended.set()

    def register(self, hotkey: str, callback: Callable[[], None]) -> None:
        """Register a global hotkey with a callback.

        hotkey uses human-friendly format: "Ctrl+Alt+1".
        """
        with self._lock:
            pynput_key = convert_hotkey_str(hotkey)
            self._bindings[pynput_key] = callback
            self._rebuild_listener()

    def unregister(self, hotkey: str) -> None:
        """Unregister a global hotkey."""
        with self._lock:
            pynput_key = convert_hotkey_str(hotkey)
            self._bindings.pop(pynput_key, None)
            self._rebuild_listener()

    def clear(self) -> None:
        """Remove all hotkey bindings."""
        with self._lock:
            self._bindings.clear()
            self._action_map.clear()
            self._rebuild_listener()

    def start(self) -> None:
        """Start the global hotkey listener."""
        if not _PYNPUT_AVAILABLE:
            logger.warning("pynput not available; global hotkeys disabled")
            return
        self._running = True
        with self._lock:
            self._rebuild_listener()

    def stop(self) -> None:
        """Stop the global hotkey listener."""
        self._running = False
        with self._lock:
            self._stop_listener()

    def suspend(self) -> None:
        """Temporarily suspend hotkey processing (e.g., during position picking)."""
        self._suspended.clear()

    def resume(self) -> None:
        """Resume hotkey processing after suspend."""
        self._suspended.set()

    def _rebuild_listener(self) -> None:
        """Stop the current listener and create a new one with current bindings."""
        self._stop_listener()

        if not _PYNPUT_AVAILABLE or not self._bindings or not self._running:
            return

        wrapped_bindings: dict[str, Callable[[], None]] = {}
        for pynput_key, cb in self._bindings.items():

            def _make_callback(callback: Callable[[], None]) -> Callable[[], None]:
                def _wrapped() -> None:
                    if not self._suspended.is_set():
                        return
                    try:
                        callback()
                    except Exception:  # noqa: BLE001
                        logger.exception("Error in hotkey callback")

                return _wrapped

            wrapped_bindings[pynput_key] = _make_callback(cb)

        try:
            self._listener = _pynput_keyboard.GlobalHotKeys(wrapped_bindings)
            self._listener.start()
            logger.info("Hotkey listener started with %d bindings", len(wrapped_bindings))
        except Exception as exc:
            logger.error("Failed to start hotkey listener: %s", exc)
            self._listener = None

    def _stop_listener(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception as exc:
                logger.debug("Failed to stop listener cleanly: %s", exc)
            self._listener = None


def simulate_click(x: int, y: int, button: str = "left") -> None:
    """Simulate a mouse click at (x, y) then restore the cursor position.

    Uses Win32 SendInput on Windows for sub-5ms round-trip (fast path).
    Falls back to pynput on other platforms.
    During the operation, user mouse movement is not overwritten: the original
    position is captured, the cursor is moved to the target, clicked, then
    restored -- all within ~13ms total.
    """
    # Try fast Win32 path first
    if _win32_simulate_click(x, y, button):
        logger.info("Simulated %s click at (%d, %d) via Win32 API", button, x, y)
        return

    # Fallback: pynput (slower, ~30-50ms)
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
    except Exception:  # noqa: BLE001
        logger.exception("Failed to simulate click at (%d, %d)", x, y)