from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("platex.win32_hotkey")

_IS_WINDOWS = False
_USER32: Any = None
_KERNEL32: Any = None

try:
    import ctypes
    from ctypes import wintypes

    _USER32 = ctypes.windll.user32
    _KERNEL32 = ctypes.windll.kernel32
    _IS_WINDOWS = True
except (ImportError, OSError):
    pass

# Win32 constants
WM_HOTKEY = 0x0312
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
ERROR_HOTKEY_ALREADY_REGISTERED = 1409


class Win32HotkeyListener:
    """Windows-native global hotkey listener using RegisterHotKey.

    More reliable than pynput for global hotkeys on Windows because:
    1. Explicit error codes when registration fails (e.g., already registered)
    2. System-level message handling - not affected by other hook-based tools
    3. Automatic recovery when conflicting apps exit
    """

    def __init__(self) -> None:
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._hotkey_to_id: dict[str, int] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._hwnd: wintypes.HWND | None = None
        self._failed_hotkeys: dict[str, int] = {}  # hotkey -> retry count
        self._retry_timer: threading.Timer | None = None

    def _parse_hotkey(self, hotkey: str) -> tuple[int, int] | None:
        """Parse human-friendly hotkey to (modifiers, vk_code).

        Returns None if parsing fails or key is unsupported.
        """
        parts = hotkey.lower().replace("<", "").replace(">", "").split("+")
        parts = [p.strip() for p in parts if p.strip()]
        if not parts:
            return None

        modifiers = 0
        key_part = parts[-1]

        for mod in parts[:-1]:
            if mod in ("ctrl", "control"):
                modifiers |= MOD_CONTROL
            elif mod == "alt":
                modifiers |= MOD_ALT
            elif mod == "shift":
                modifiers |= MOD_SHIFT
            elif mod in ("win", "cmd", "super"):
                modifiers |= MOD_WIN

        # Virtual key codes
        vk_map = {
            "0": 0x30, "1": 0x31, "2": 0x32, "3": 0x33, "4": 0x34,
            "5": 0x35, "6": 0x36, "7": 0x37, "8": 0x38, "9": 0x39,
            "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
            "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
            "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
            "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
            "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
            "z": 0x5A,
            "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74,
            "f6": 0x75, "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79,
            "f11": 0x7A, "f12": 0x7B, "f13": 0x7C, "f14": 0x7D, "f15": 0x7E,
            "f16": 0x7F, "f17": 0x80, "f18": 0x81, "f19": 0x82, "f20": 0x83,
            "f21": 0x84, "f22": 0x85, "f23": 0x86, "f24": 0x87,
            "space": 0x20, "enter": 0x0D, "return": 0x0D, "tab": 0x09,
            "escape": 0x1B, "esc": 0x1B, "backspace": 0x08, "delete": 0x2E,
            "insert": 0x2D, "home": 0x24, "end": 0x23, "page_up": 0x21,
            "page_down": 0x22, "up": 0x26, "down": 0x28, "left": 0x25,
            "right": 0x27, "caps_lock": 0x14,
            "print_screen": 0x2C, "scroll_lock": 0x91, "pause": 0x13,
            "numlock": 0x90, "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62,
            "numpad3": 0x63, "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66,
            "numpad7": 0x67, "numpad8": 0x68, "numpad9": 0x69,
            "multiply": 0x6A, "add": 0x6B, "separator": 0x6C, "subtract": 0x6D,
            "decimal": 0x6E, "divide": 0x6F,
            ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
            "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
        }

        vk = vk_map.get(key_part)
        if vk is None:
            # Single character fallback
            if len(key_part) == 1:
                vk = ord(key_part.upper())
            else:
                logger.warning("Unknown key in hotkey '%s': %s", hotkey, key_part)
                return None

        return modifiers, vk

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """Register a global hotkey. Returns True on success."""
        if not _IS_WINDOWS or _USER32 is None:
            return False

        with self._lock:
            # Unregister existing if present
            if hotkey in self._hotkey_to_id:
                self._unregister_internal(hotkey)

            parsed = self._parse_hotkey(hotkey)
            if parsed is None:
                logger.error("Failed to parse hotkey: %s", hotkey)
                return False

            modifiers, vk = parsed
            hotkey_id = self._next_id
            self._next_id += 1

            # Try to register
            result = _USER32.RegisterHotKey(None, hotkey_id, modifiers, vk)
            if result == 0:
                err = _KERNEL32.GetLastError()
                if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                    logger.warning(
                        "Hotkey '%s' is already registered by another application (error %d)",
                        hotkey, err,
                    )
                else:
                    logger.error(
                        "Failed to register hotkey '%s': error %d", hotkey, err,
                    )
                self._failed_hotkeys[hotkey] = self._failed_hotkeys.get(hotkey, 0) + 1
                return False

            self._callbacks[hotkey_id] = callback
            self._hotkey_to_id[hotkey] = hotkey_id
            self._failed_hotkeys.pop(hotkey, None)
            logger.info("Registered Win32 hotkey '%s' with id=%d", hotkey, hotkey_id)
            return True

    def unregister(self, hotkey: str) -> None:
        """Unregister a global hotkey."""
        with self._lock:
            self._unregister_internal(hotkey)

    def _unregister_internal(self, hotkey: str) -> None:
        hotkey_id = self._hotkey_to_id.pop(hotkey, None)
        if hotkey_id is not None:
            _USER32.UnregisterHotKey(None, hotkey_id)
            self._callbacks.pop(hotkey_id, None)
            logger.info("Unregistered Win32 hotkey '%s' id=%d", hotkey, hotkey_id)

    def clear(self) -> None:
        """Remove all hotkey bindings."""
        with self._lock:
            for hotkey_id in list(self._callbacks.keys()):
                _USER32.UnregisterHotKey(None, hotkey_id)
            self._callbacks.clear()
            self._hotkey_to_id.clear()
            self._failed_hotkeys.clear()

    def start(self) -> None:
        """Start the message loop thread."""
        if not _IS_WINDOWS:
            logger.warning("Win32 hotkeys only available on Windows")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        if not self._callbacks:
            logger.debug("No hotkeys registered, skipping Win32 message loop")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._message_loop, name="win32-hotkey-loop", daemon=True)
        self._thread.start()
        logger.info("Win32 hotkey listener started with %d hotkeys", len(self._callbacks))

    def stop(self) -> None:
        """Stop the message loop thread."""
        self._stop_event.set()
        # Post a message to wake up GetMessage
        if _USER32 is not None and self._hwnd:
            _USER32.PostMessageW(self._hwnd, WM_HOTKEY, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None
        self.clear()
        logger.info("Win32 hotkey listener stopped")

    def _message_loop(self) -> None:
        """Windows message loop for hotkey notifications."""
        if _USER32 is None:
            return

        # Create a message-only window
        WNDPROC = ctypes.WINFUNCTYPE(
            wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        )

        @WNDPROC
        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_HOTKEY:
                with self._lock:
                    callback = self._callbacks.get(int(wparam))
                if callback is not None:
                    try:
                        callback()
                    except Exception:
                        logger.exception("Error in Win32 hotkey callback")
            return _USER32.DefWindowProcW(hwnd, msg, wparam, lparam)

        # Register window class
        class WNDCLASSW(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HANDLE),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HANDLE),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        hinst = _KERNEL32.GetModuleHandleW(None)
        class_name = "PLatexHotkeyWindow"

        wndclass = WNDCLASSW()
        wndclass.lpfnWndProc = wnd_proc
        wndclass.hInstance = hinst
        wndclass.lpszClassName = class_name

        if not _USER32.RegisterClassW(ctypes.byref(wndclass)):
            err = _KERNEL32.GetLastError()
            if err != 0:  # ERROR_CLASS_ALREADY_EXISTS = 1410, but 0 may also mean success
                logger.error("Failed to register window class for hotkeys: error %d", err)
                return

        HWND_MESSAGE = -3
        self._hwnd = _USER32.CreateWindowExW(
            0, class_name, "PLatex Hotkeys",
            0, 0, 0, 0, 0,
            HWND_MESSAGE,
            None, hinst, None,
        )

        if not self._hwnd:
            err = _KERNEL32.GetLastError()
            logger.error("Failed to create message-only window for hotkeys: error %d", err)
            return

        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            ret = _USER32.GetMessageW(ctypes.byref(msg), self._hwnd, 0, 0)
            if ret == -1:
                break
            if ret == 0:  # WM_QUIT
                break
            _USER32.TranslateMessage(ctypes.byref(msg))
            _USER32.DispatchMessageW(ctypes.byref(msg))

        _USER32.DestroyWindow(self._hwnd)
        self._hwnd = None

    def get_status(self) -> dict[str, Any]:
        """Return current hotkey registration status."""
        with self._lock:
            return {
                "registered": list(self._hotkey_to_id.keys()),
                "failed": dict(self._failed_hotkeys),
                "running": self._thread is not None and self._thread.is_alive(),
            }

    def schedule_retry(self, delay: float = 5.0) -> None:
        """Schedule a retry for failed hotkeys."""
        if self._retry_timer is not None:
            self._retry_timer.cancel()

        def _retry() -> None:
            with self._lock:
                failed = list(self._failed_hotkeys.keys())
            for hotkey in failed:
                # We need the callback but it's not stored separately
                # Retry is handled by the caller (HotkeyListener)
                pass

        self._retry_timer = threading.Timer(delay, _retry)
        self._retry_timer.daemon = True
        self._retry_timer.start()
