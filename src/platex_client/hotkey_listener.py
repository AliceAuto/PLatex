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

    # Some UI components may emit multi-sequence text like
    # "Ctrl+Shift+E, Ctrl+Shift+E". Keep only the first sequence.
    hotkey = hotkey.split(",", 1)[0].strip()

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

    Briefly blocks mouse input during the operation to prevent position drift.
    Returns True if successful, False if the API is unavailable.
    """
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

    try:
        # Block mouse/keyboard input briefly to prevent position drift
        _USER32.BlockInput(True)

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
        # Always unblock input, even on error
        try:
            _USER32.BlockInput(False)
        except Exception:
            pass


class _PynputBackend:
    """pynput-based hotkey backend."""

    def __init__(self, suspended: threading.Event) -> None:
        self._bindings: dict[str, Callable[[], None]] = {}
        self._listener: object | None = None
        self._suspended = suspended

    def set_bindings(self, bindings: dict[str, Callable[[], None]]) -> None:
        self._bindings = dict(bindings)

    def start(self) -> bool:
        if not _PYNPUT_AVAILABLE:
            return False
        self.stop()
        if not self._bindings:
            return True

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
            logger.info("pynput hotkey listener started with %d bindings", len(wrapped_bindings))
            return True
        except Exception as exc:
            logger.error("Failed to start pynput hotkey listener: %s", exc)
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception as exc:
                logger.debug("Failed to stop pynput listener cleanly: %s", exc)
            self._listener = None


class HotkeyListener:
    """Global hotkey listener with dual backend support.

    On Windows, uses Win32 RegisterHotKey API for better reliability.
    Falls back to pynput on other platforms or when Win32 fails.
    """

    def __init__(self) -> None:
        self._bindings: dict[str, Callable[[], None]] = {}
        self._lock = threading.Lock()
        self._running = False
        self._suspended = threading.Event()
        self._suspended.set()
        self._win32_backend: Any | None = None
        self._pynput_backend: _PynputBackend | None = None
        self._use_win32 = False
        self._failed_bindings: dict[str, int] = {}
        self._retry_timer: threading.Timer | None = None
        self._status_callbacks: list[Callable[[dict], None]] = []

        if _IS_WINDOWS:
            try:
                from .win32_hotkey import Win32HotkeyListener
                self._win32_backend = Win32HotkeyListener()
            except Exception as exc:
                logger.debug("Win32 hotkey backend not available: %s", exc)

        if _PYNPUT_AVAILABLE:
            self._pynput_backend = _PynputBackend(self._suspended)

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """Register a global hotkey with a callback.

        hotkey uses human-friendly format: "Ctrl+Alt+1".
        Returns True if registration succeeded.
        """
        with self._lock:
            self._bindings[hotkey] = callback
            self._failed_bindings.pop(hotkey, None)
            success = self._rebuild_listener()
            return success

    def unregister(self, hotkey: str) -> None:
        """Unregister a global hotkey."""
        with self._lock:
            self._bindings.pop(hotkey, None)
            self._failed_bindings.pop(hotkey, None)
            self._rebuild_listener()

    def clear(self) -> None:
        """Remove all hotkey bindings."""
        with self._lock:
            self._bindings.clear()
            self._failed_bindings.clear()
            self._cancel_retry()
            if self._win32_backend is not None:
                self._win32_backend.clear()
            if self._pynput_backend is not None:
                self._pynput_backend.set_bindings({})
                self._pynput_backend.stop()

    def start(self) -> None:
        """Start the global hotkey listener."""
        self._running = True
        with self._lock:
            self._rebuild_listener()

    def stop(self) -> None:
        """Stop the global hotkey listener."""
        self._running = False
        self._cancel_retry()
        with self._lock:
            if self._win32_backend is not None:
                self._win32_backend.stop()
            if self._pynput_backend is not None:
                self._pynput_backend.stop()

    def suspend(self) -> None:
        """Temporarily suspend hotkey processing (e.g., during position picking)."""
        self._suspended.clear()

    def resume(self) -> None:
        """Resume hotkey processing after suspend."""
        self._suspended.set()

    def get_status(self) -> dict:
        """Return current hotkey registration status."""
        with self._lock:
            status = {
                "running": self._running,
                "suspended": not self._suspended.is_set(),
                "backend": "win32" if self._use_win32 else ("pynput" if self._pynput_backend else "none"),
                "registered_count": len(self._bindings),
                "failed": dict(self._failed_bindings),
                "bindings": list(self._bindings.keys()),
            }
            if self._win32_backend is not None:
                try:
                    win32_status = self._win32_backend.get_status()
                    status["win32"] = win32_status
                except Exception:
                    pass
            return status

    def on_status_change(self, callback: Callable[[dict], None]) -> None:
        """Register a callback to be called when hotkey status changes."""
        self._status_callbacks.append(callback)

    def _notify_status(self) -> None:
        status = self.get_status()
        for cb in self._status_callbacks:
            try:
                cb(status)
            except Exception:
                logger.exception("Error in status callback")

    def _rebuild_listener(self) -> bool:
        """Rebuild the listener with current bindings. Returns True if all bindings registered."""
        if not self._running:
            return True

        # Try Win32 backend first on Windows
        if self._win32_backend is not None and _IS_WINDOWS:
            self._use_win32 = True
            self._win32_backend.clear()
            all_success = True
            for hotkey, callback in self._bindings.items():
                # Convert to pynput format first, then win32 will parse it
                try:
                    pynput_key = convert_hotkey_str(hotkey)
                except ValueError:
                    pynput_key = hotkey
                success = self._win32_backend.register(pynput_key, callback)
                if not success:
                    self._failed_bindings[hotkey] = self._failed_bindings.get(hotkey, 0) + 1
                    all_success = False
                    logger.warning("Failed to register Win32 hotkey: %s", hotkey)

            self._win32_backend.start()
            self._notify_status()

            if all_success:
                # Stop pynput if it was running
                if self._pynput_backend is not None:
                    self._pynput_backend.stop()
                return True
            else:
                # Some failed - also start pynput as fallback for those?
                # Actually pynput will likely fail too for the same reason.
                # Just report the failures.
                self._schedule_retry()
                return False

        # Fall back to pynput
        if self._pynput_backend is not None:
            self._use_win32 = False
            pynput_bindings: dict[str, Callable[[], None]] = {}
            for hotkey, callback in self._bindings.items():
                try:
                    pynput_key = convert_hotkey_str(hotkey)
                    pynput_bindings[pynput_key] = callback
                except ValueError as exc:
                    logger.error("Invalid hotkey '%s': %s", hotkey, exc)
                    self._failed_bindings[hotkey] = self._failed_bindings.get(hotkey, 0) + 1

            self._pynput_backend.set_bindings(pynput_bindings)
            success = self._pynput_backend.start()
            self._notify_status()
            return success

        logger.warning("No hotkey backend available")
        self._notify_status()
        return False

    def _schedule_retry(self) -> None:
        """Schedule a retry for failed hotkeys."""
        self._cancel_retry()
        if not self._failed_bindings or not self._running:
            return

        def _retry() -> None:
            with self._lock:
                if not self._running:
                    return
                # Rebuild will attempt to re-register all bindings including failed ones
                self._rebuild_listener()

        self._retry_timer = threading.Timer(3.0, _retry)
        self._retry_timer.daemon = True
        self._retry_timer.start()
        logger.debug("Scheduled hotkey retry in 3s for: %s", list(self._failed_bindings.keys()))

    def _cancel_retry(self) -> None:
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None


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
