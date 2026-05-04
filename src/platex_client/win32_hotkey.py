from __future__ import annotations

import ctypes
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from .platform_utils import IS_WINDOWS, KERNEL32, USER32
from .win32_utils import register_window_class, create_message_window, destroy_message_window

logger = logging.getLogger("platex.win32_hotkey")

if IS_WINDOWS:
    from ctypes import wintypes

WM_HOTKEY = 0x0312
_WM_USER_STOP = 0x0401
_WM_USER_REGISTER = 0x0402
_WM_USER_UNREGISTER = 0x0403
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
ERROR_HOTKEY_ALREADY_REGISTERED = 1409
ERROR_CLASS_ALREADY_EXISTS = 1410

_WH_KEYBOARD_LL = 13
_WM_KEYDOWN = 0x0100
_WM_SYSKEYDOWN = 0x0104
_WM_KEYUP = 0x0101
_WM_SYSKEYUP = 0x0105
_WM_LL_HOOK_QUIT = 0x0501

_VK_SHIFT = 0x10
_VK_CONTROL = 0x11
_VK_MENU = 0x12
_VK_LWIN = 0x5B
_VK_RWIN = 0x5C

_MODIFIER_VK_TO_FLAG = {
    _VK_SHIFT: MOD_SHIFT,
    _VK_CONTROL: MOD_CONTROL,
    _VK_MENU: MOD_ALT,
    0xA0: MOD_SHIFT,
    0xA1: MOD_SHIFT,
    0xA2: MOD_CONTROL,
    0xA3: MOD_CONTROL,
    0xA4: MOD_ALT,
    0xA5: MOD_ALT,
    _VK_LWIN: MOD_WIN,
    _VK_RWIN: MOD_WIN,
}


class _KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

_MAX_RETRY_COUNT = 10
_MAX_RETRY_DELAY = 30.0

_instance_counter = 0
_instance_lock = threading.Lock()


class Win32HotkeyListener:

    def __init__(self) -> None:
        global _instance_counter
        with _instance_lock:
            _instance_counter += 1
            self._instance_id = _instance_counter

        self._callbacks: dict[int, Callable[[], None]] = {}
        self._hotkey_to_id: dict[str, int] = {}
        self._next_id = 1
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._hwnd: Any = None
        self._failed_hotkeys: dict[str, int] = {}
        self._retry_timer: threading.Timer | None = None
        self._pending: dict[str, tuple[int, int, int, Callable[[], None]]] = {}
        self._pending_unregisters: list[int] = []
        self._ready_event = threading.Event()
        self._wnd_proc_ref: Any = None
        self._wndproc_type: Any = None

    _MODIFIER_NAMES = {"ctrl", "control", "alt", "shift", "win", "cmd", "super", "windows", "meta"}

    def _parse_hotkey(self, hotkey: str) -> tuple[int, int] | None:
        parts = hotkey.lower().replace("<", "").replace(">", "").split("+")
        parts = [p.strip() for p in parts if p.strip()]
        if not parts:
            return None

        modifiers = 0
        key_part = parts[-1]

        if key_part in self._MODIFIER_NAMES:
            logger.warning("Bare modifier '%s' in hotkey '%s' is not a valid hotkey (needs a key)", key_part, hotkey)
            return None

        for mod in parts[:-1]:
            if mod in ("ctrl", "control"):
                modifiers |= MOD_CONTROL
            elif mod == "alt":
                modifiers |= MOD_ALT
            elif mod == "shift":
                modifiers |= MOD_SHIFT
            elif mod in ("win", "cmd", "super", "windows", "meta"):
                modifiers |= MOD_WIN

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
            "backtab": 0x09,
            "escape": 0x1B, "esc": 0x1B, "backspace": 0x08, "delete": 0x2E,
            "del": 0x2E, "insert": 0x2D, "ins": 0x2D, "home": 0x24, "end": 0x23,
            "page_up": 0x21, "prior": 0x21, "pgup": 0x21,
            "page_down": 0x22, "next": 0x22, "pgdown": 0x22, "pgdn": 0x22,
            "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
            "caps_lock": 0x14, "capslock": 0x14,
            "print_screen": 0x2C, "sysrq": 0x2C, "prtsc": 0x2C,
            "scroll_lock": 0x91, "scrolllock": 0x91,
            "pause": 0x13, "break": 0x13,
            "num_lock": 0x90, "numlock": 0x90,
            "menu": 0x5D, "help": 0x2F, "clear": 0x0C, "print": 0x2C,
            "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62,
            "numpad3": 0x63, "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66,
            "numpad7": 0x67, "numpad8": 0x68, "numpad9": 0x69,
            "multiply": 0x6A, "add": 0x6B, "separator": 0x6C, "subtract": 0x6D,
            "decimal": 0x6E, "divide": 0x6F,
            "volume_down": 0xAE, "volume_mute": 0xAD, "volume_up": 0xAF,
            "media_next": 0xB0, "media_prev": 0xB1, "media_stop": 0xB2,
            "media_play_pause": 0xB3, "media_play": 0xB3,
            "launch_mail": 0xB4, "launch_media": 0xB5,
            "browser_back": 0xA6, "browser_forward": 0xA7,
            "browser_refresh": 0xA8, "browser_stop": 0xA9,
            "browser_search": 0xAA, "browser_favorites": 0xAB,
            "browser_home": 0xAC,
            ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
            "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
        }

        vk = vk_map.get(key_part)
        if vk is None:
            if len(key_part) == 1:
                vk = ord(key_part.upper())
            else:
                logger.warning("Unknown key in hotkey '%s': %s", hotkey, key_part)
                return None

        return modifiers, vk

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        if not IS_WINDOWS or USER32 is None:
            return False

        with self._lock:
            if hotkey in self._hotkey_to_id:
                self._unregister_internal(hotkey)

            parsed = self._parse_hotkey(hotkey)
            if parsed is None:
                logger.error("Failed to parse hotkey: %s", hotkey)
                return False

            modifiers, vk = parsed
            hotkey_id = self._next_id
            self._next_id += 1

            self._pending[hotkey] = (modifiers, vk, hotkey_id, callback)
            self._hotkey_to_id[hotkey] = hotkey_id
            self._callbacks[hotkey_id] = callback
            self._failed_hotkeys.pop(hotkey, None)
            logger.debug("Queued Win32 hotkey '%s' for registration (id=%d)", hotkey, hotkey_id)

            hwnd = self._hwnd
            thread_alive = self._thread is not None and self._thread.is_alive()

            if thread_alive and hwnd:
                try:
                    USER32.PostMessageW(hwnd, _WM_USER_REGISTER, 0, 0)
                except Exception:
                    logger.debug("PostMessageW failed for register notification")

        return True

    def unregister(self, hotkey: str) -> None:
        with self._lock:
            self._unregister_internal(hotkey)

    def _unregister_internal(self, hotkey: str) -> None:
        hotkey_id = self._hotkey_to_id.pop(hotkey, None)
        if hotkey_id is not None:
            if hotkey not in self._pending:
                self._pending_unregisters.append(hotkey_id)
                hwnd = self._hwnd
                thread_alive = self._thread is not None and self._thread.is_alive()
                if thread_alive and hwnd:
                    try:
                        USER32.PostMessageW(hwnd, _WM_USER_UNREGISTER, 0, 0)
                    except Exception:
                        logger.debug("PostMessageW failed for unregister notification")
            self._callbacks.pop(hotkey_id, None)
            self._pending.pop(hotkey, None)
            self._failed_hotkeys.pop(hotkey, None)
            logger.info("Unregistered Win32 hotkey '%s' id=%d", hotkey, hotkey_id)

    def clear(self) -> None:
        with self._lock:
            hotkey_ids = list(self._callbacks.keys())
            self._pending_unregisters.extend(hotkey_ids)
            self._callbacks.clear()
            self._hotkey_to_id.clear()
            self._failed_hotkeys.clear()
            self._pending.clear()
            self._next_id = 1
            if self._retry_timer is not None:
                self._retry_timer.cancel()
                self._retry_timer = None
            hwnd = self._hwnd
            thread_alive = self._thread is not None and self._thread.is_alive()
        if thread_alive and hwnd and hotkey_ids:
            try:
                USER32.PostMessageW(hwnd, _WM_USER_UNREGISTER, 0, 0)
            except Exception:
                logger.debug("PostMessageW failed for clear notification")
        if not thread_alive:
            self._wnd_proc_ref = None
            self._wndproc_type = None

    def start(self) -> None:
        if not IS_WINDOWS:
            logger.warning("Win32 hotkeys only available on Windows")
            return

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                hwnd = self._hwnd
                has_pending = bool(self._pending)
                if hwnd and has_pending:
                    try:
                        USER32.PostMessageW(hwnd, _WM_USER_REGISTER, 0, 0)
                    except Exception:
                        logger.debug("PostMessageW failed for start notification")
                return

            if not self._callbacks and not self._pending:
                logger.debug("No hotkeys registered, skipping Win32 message loop")
                return

        self._stop_event.clear()
        self._ready_event.clear()
        self._thread = threading.Thread(target=self._message_loop, name="win32-hotkey-loop", daemon=True)
        self._thread.start()
        self._ready_event.wait(timeout=5.0)
        logger.info("Win32 hotkey listener started: %d registered, %d failed",
                     len(self._callbacks), len(self._failed_hotkeys))

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            hwnd = self._hwnd
            self._hwnd = None
            if self._retry_timer is not None:
                self._retry_timer.cancel()
                self._retry_timer = None
        if USER32 is not None and hwnd:
            try:
                USER32.PostMessageW(hwnd, _WM_USER_STOP, 0, 0)
            except Exception:
                logger.debug("Failed to post stop message to hotkey window (may already be destroyed)")
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._unregister_all_win32()
        logger.info("Win32 hotkey listener stopped")

    def _unregister_all_win32(self) -> None:
        if USER32 is None:
            return
        with self._lock:
            hotkey_ids = list(self._callbacks.keys())
        for hotkey_id in hotkey_ids:
            try:
                USER32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                pass

    def _register_pending_hotkeys(self) -> None:
        with self._lock:
            pending = dict(self._pending)
            self._pending.clear()

        succeeded: list[str] = []
        for hotkey, (modifiers, vk, hotkey_id, callback) in pending.items():
            try:
                result = USER32.RegisterHotKey(None, hotkey_id, modifiers, vk)
            except Exception:
                result = 0
                logger.error("RegisterHotKey raised exception for '%s'", hotkey)
            if result == 0:
                err = ctypes.get_last_error()
                if err == ERROR_HOTKEY_ALREADY_REGISTERED:
                    logger.warning(
                        "Hotkey '%s' is already registered by another application (error %d)",
                        hotkey, err,
                    )
                else:
                    logger.error(
                        "Failed to register hotkey '%s': error %d", hotkey, err,
                    )
                with self._lock:
                    self._failed_hotkeys[hotkey] = self._failed_hotkeys.get(hotkey, 0) + 1
            else:
                logger.info("Registered Win32 hotkey '%s' with id=%d", hotkey, hotkey_id)
                succeeded.append(hotkey)

        with self._lock:
            for hotkey in succeeded:
                self._failed_hotkeys.pop(hotkey, None)
            if self._failed_hotkeys:
                self._schedule_retry()

    def _process_pending_unregisters(self) -> None:
        with self._lock:
            ids = list(self._pending_unregisters)
            self._pending_unregisters.clear()
        for hotkey_id in ids:
            try:
                USER32.UnregisterHotKey(None, hotkey_id)
            except Exception:
                logger.debug("Failed to unregister Win32 hotkey id=%d", hotkey_id)

    def _message_loop(self) -> None:
        if USER32 is None or KERNEL32 is None:
            self._ready_event.set()
            return

        if self._stop_event.is_set():
            self._ready_event.set()
            return

        self._wndproc_type = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            ctypes.c_ssize_t, ctypes.c_ssize_t,
        )
        WNDPROC = self._wndproc_type

        @WNDPROC
        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_HOTKEY:
                hotkey_id = int(wparam)
                callback = self._callbacks.get(hotkey_id)
                if callback is not None:
                    try:
                        callback()
                    except Exception:
                        logger.exception("Error executing hotkey callback for id=%d", hotkey_id)
                else:
                    logger.debug("Received WM_HOTKEY for unknown id=%d", hotkey_id)
                return 0
            if msg == _WM_USER_STOP:
                USER32.PostQuitMessage(0)
                return 0
            elif msg == _WM_USER_REGISTER:
                self._register_pending_hotkeys()
                return 0
            elif msg == _WM_USER_UNREGISTER:
                self._process_pending_unregisters()
                return 0
            return USER32.DefWindowProcW(hwnd, msg, wparam, lparam)

        self._wnd_proc_ref = wnd_proc

        hinst = KERNEL32.GetModuleHandleW(None) if KERNEL32 else None
        class_name = f"PLatexHotkeyWnd_{self._instance_id}"

        if self._stop_event.is_set():
            self._ready_event.set()
            return

        if not register_window_class(class_name, self._wnd_proc_ref, WNDPROC, hinst):
            self._ready_event.set()
            return

        if self._stop_event.is_set():
            destroy_message_window(0, class_name, hinst)
            self._ready_event.set()
            return

        hwnd = create_message_window(class_name, "PLatex Hotkeys", hinst)
        if not hwnd:
            destroy_message_window(0, class_name, hinst)
            self._ready_event.set()
            return

        with self._lock:
            self._hwnd = hwnd

        self._register_pending_hotkeys()

        self._ready_event.set()

        msg = wintypes.MSG()
        try:
            while not self._stop_event.is_set():
                try:
                    ret = USER32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                except Exception:
                    logger.exception("GetMessageW raised unexpected exception")
                    break
                if ret == -1:
                    err = ctypes.get_last_error()
                    logger.error("GetMessageW returned -1 (error %d)", err)
                    break
                if ret == 0:
                    break
                if msg.message == WM_HOTKEY:
                    hotkey_id = int(msg.wParam)
                    callback = self._callbacks.get(hotkey_id)
                    if callback is not None:
                        try:
                            callback()
                        except Exception:
                            logger.exception("Error executing hotkey callback for id=%d", hotkey_id)
                    else:
                        logger.debug("Received WM_HOTKEY for unknown id=%d", hotkey_id)
                    continue
                try:
                    USER32.TranslateMessage(ctypes.byref(msg))
                    USER32.DispatchMessageW(ctypes.byref(msg))
                except Exception:
                    logger.exception("Error dispatching window message")
        except Exception:
            logger.exception("Unexpected error in hotkey message loop")
        finally:
            with self._lock:
                self._hwnd = None
            destroy_message_window(hwnd, class_name, hinst)
            with self._lock:
                self._wnd_proc_ref = None
                self._wndproc_type = None

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "registered": list(self._hotkey_to_id.keys()),
                "failed": dict(self._failed_hotkeys),
                "running": self._thread is not None and self._thread.is_alive(),
            }

    def schedule_retry(self, delay: float = 5.0) -> None:
        self._schedule_retry(delay)

    def _schedule_retry(self, delay: float = 5.0) -> None:
        with self._lock:
            if self._retry_timer is not None:
                self._retry_timer.cancel()
                self._retry_timer = None

            if not self._failed_hotkeys:
                return
            for hotkey, count in self._failed_hotkeys.items():
                if count >= _MAX_RETRY_COUNT:
                    logger.warning("Giving up retrying hotkey '%s' after %d failures", hotkey, count)
            still_retryable = {k: v for k, v in self._failed_hotkeys.items() if v < _MAX_RETRY_COUNT}
            if not still_retryable:
                return
            hwnd = self._hwnd
            thread_alive = self._thread is not None and self._thread.is_alive()

            if not thread_alive or not hwnd:
                return

            def _retry() -> None:
                with self._lock:
                    if self._stop_event.is_set():
                        return
                    if self._retry_timer is None:
                        return
                    if self._thread is None or not self._thread.is_alive():
                        return
                    hwnd_now = self._hwnd
                    for hotkey in list(self._failed_hotkeys.keys()):
                        if self._failed_hotkeys[hotkey] >= _MAX_RETRY_COUNT:
                            continue
                        parsed = self._parse_hotkey(hotkey)
                        if parsed is None:
                            continue
                        modifiers, vk = parsed
                        hotkey_id = self._next_id
                        self._next_id += 1
                        old_id = self._hotkey_to_id.get(hotkey)
                        callback = self._callbacks.get(old_id) if old_id is not None else None
                        if callback is None:
                            continue
                        if old_id is not None:
                            self._callbacks.pop(old_id, None)
                        self._hotkey_to_id[hotkey] = hotkey_id
                        self._callbacks[hotkey_id] = callback
                        self._pending[hotkey] = (modifiers, vk, hotkey_id, callback)
                        del self._failed_hotkeys[hotkey]
                    has_failed = bool(self._failed_hotkeys)

                if hwnd_now:
                    try:
                        USER32.PostMessageW(hwnd_now, _WM_USER_REGISTER, 0, 0)
                    except Exception:
                        logger.debug("Failed to post register message during retry (window may be destroyed)")

                if has_failed:
                    next_delay = min(delay * 1.5, _MAX_RETRY_DELAY)
                    self._schedule_retry(next_delay)

            self._retry_timer = threading.Timer(delay, _retry)
            self._retry_timer.daemon = True
            self._retry_timer.start()


def _parse_hotkey_to_vk(hotkey: str) -> tuple[int, int] | None:
    parts = hotkey.lower().replace("<", "").replace(">", "").split("+")
    parts = [p.strip() for p in parts if p.strip()]
    if not parts:
        return None

    modifiers = 0
    key_part = parts[-1]

    _MODIFIER_NAMES = {"ctrl", "control", "alt", "shift", "win", "cmd", "super", "windows", "meta"}
    if key_part in _MODIFIER_NAMES:
        return None

    for mod in parts[:-1]:
        if mod in ("ctrl", "control"):
            modifiers |= MOD_CONTROL
        elif mod == "alt":
            modifiers |= MOD_ALT
        elif mod == "shift":
            modifiers |= MOD_SHIFT
        elif mod in ("win", "cmd", "super", "windows", "meta"):
            modifiers |= MOD_WIN

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
        "backtab": 0x09,
        "escape": 0x1B, "esc": 0x1B, "backspace": 0x08, "delete": 0x2E,
        "del": 0x2E, "insert": 0x2D, "ins": 0x2D, "home": 0x24, "end": 0x23,
        "page_up": 0x21, "prior": 0x21, "pgup": 0x21,
        "page_down": 0x22, "next": 0x22, "pgdown": 0x22, "pgdn": 0x22,
        "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
        "caps_lock": 0x14, "capslock": 0x14,
        "print_screen": 0x2C, "sysrq": 0x2C, "prtsc": 0x2C,
        "scroll_lock": 0x91, "scrolllock": 0x91,
        "pause": 0x13, "break": 0x13,
        "num_lock": 0x90, "numlock": 0x90,
        "menu": 0x5D, "help": 0x2F, "clear": 0x0C, "print": 0x2C,
        "numpad0": 0x60, "numpad1": 0x61, "numpad2": 0x62,
        "numpad3": 0x63, "numpad4": 0x64, "numpad5": 0x65, "numpad6": 0x66,
        "numpad7": 0x67, "numpad8": 0x68, "numpad9": 0x69,
        "multiply": 0x6A, "add": 0x6B, "separator": 0x6C, "subtract": 0x6D,
        "decimal": 0x6E, "divide": 0x6F,
        "volume_down": 0xAE, "volume_mute": 0xAD, "volume_up": 0xAF,
        "media_next": 0xB0, "media_prev": 0xB1, "media_stop": 0xB2,
        "media_play_pause": 0xB3, "media_play": 0xB3,
        "launch_mail": 0xB4, "launch_media": 0xB5,
        "browser_back": 0xA6, "browser_forward": 0xA7,
        "browser_refresh": 0xA8, "browser_stop": 0xA9,
        "browser_search": 0xAA, "browser_favorites": 0xAB,
        "browser_home": 0xAC,
        ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
        "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    }

    vk = vk_map.get(key_part)
    if vk is None:
        if len(key_part) == 1:
            vk = ord(key_part.upper())
        else:
            return None

    return modifiers, vk


class LowLevelKeyboardHook:
    def __init__(self) -> None:
        self._hooks: dict[tuple[int, int], Callable[[], None]] = {}
        self._hook_handle: Any = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._current_modifiers: int = 0
        self._pressed_keys: set[int] = set()
        self._hook_proc_ref: Any = None
        self._ready_event = threading.Event()

    def register(self, modifiers: int, vk: int, callback: Callable[[], None]) -> None:
        with self._lock:
            self._hooks[(modifiers, vk)] = callback

    def unregister(self, modifiers: int, vk: int) -> None:
        with self._lock:
            self._hooks.pop((modifiers, vk), None)

    def clear(self) -> None:
        with self._lock:
            self._hooks.clear()

    def start(self) -> None:
        if not IS_WINDOWS or USER32 is None:
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._ready_event.clear()
        self._thread = threading.Thread(
            target=self._hook_loop, name="ll-keyboard-hook", daemon=True
        )
        self._thread.start()
        self._ready_event.wait(timeout=5.0)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            tid = self._thread.ident
            if tid:
                try:
                    USER32.PostThreadMessageW(tid, _WM_LL_HOOK_QUIT, 0, 0)
                except Exception:
                    pass
            self._thread.join(timeout=2.0)
        self._thread = None
        self._hook_handle = None

    def _sync_modifier_state(self) -> None:
        if USER32 is None:
            return
        self._current_modifiers = 0
        for vk, mod_flag in _MODIFIER_VK_TO_FLAG.items():
            if USER32.GetKeyState(vk) & 0x8000:
                self._current_modifiers |= mod_flag

    def _hook_loop(self) -> None:
        if USER32 is None or KERNEL32 is None:
            self._ready_event.set()
            return

        hook_proc_type = ctypes.CFUNCTYPE(
            ctypes.c_ssize_t, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_ssize_t
        )

        hook_self = self

        @hook_proc_type
        def hook_proc(nCode, wParam, lParam):
            if nCode >= 0 and not hook_self._stop_event.is_set():
                msg = int(wParam)
                if msg in (_WM_KEYDOWN, _WM_SYSKEYDOWN):
                    try:
                        kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                        hook_self._on_key_down(kb.vkCode)
                    except Exception:
                        logger.exception("Error in LL keyboard hook key-down handler")
                elif msg in (_WM_KEYUP, _WM_SYSKEYUP):
                    try:
                        kb = ctypes.cast(lParam, ctypes.POINTER(_KBDLLHOOKSTRUCT)).contents
                        hook_self._on_key_up(kb.vkCode)
                    except Exception:
                        logger.exception("Error in LL keyboard hook key-up handler")

            return USER32.CallNextHookEx(None, nCode, wParam, lParam)

        self._hook_proc_ref = hook_proc

        USER32.SetWindowsHookExW.restype = ctypes.c_void_p
        USER32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD
        ]
        USER32.UnhookWindowsHookEx.restype = wintypes.BOOL
        USER32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
        USER32.CallNextHookEx.restype = ctypes.c_ssize_t
        USER32.CallNextHookEx.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_ssize_t
        ]

        hinst = ctypes.pythonapi._handle
        self._hook_handle = USER32.SetWindowsHookExW(
            _WH_KEYBOARD_LL, hook_proc, hinst, 0
        )

        if not self._hook_handle:
            err = ctypes.get_last_error()
            logger.error("Failed to install low-level keyboard hook: error %d", err)
            self._ready_event.set()
            return

        self._sync_modifier_state()

        msg = wintypes.MSG()
        USER32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        self._ready_event.set()
        logger.info("Low-level keyboard hook installed with %d bindings", len(self._hooks))

        try:
            while not self._stop_event.is_set():
                ret = USER32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret == 0 or ret == -1:
                    break
                if msg.message == _WM_LL_HOOK_QUIT:
                    break
                USER32.TranslateMessage(ctypes.byref(msg))
                USER32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            logger.exception("Error in low-level keyboard hook message loop")
        finally:
            if self._hook_handle:
                try:
                    USER32.UnhookWindowsHookEx(self._hook_handle)
                except Exception:
                    pass
                self._hook_handle = None
            self._hook_proc_ref = None
            self._pressed_keys.clear()
            self._current_modifiers = 0
            logger.info("Low-level keyboard hook removed")

    def _on_key_down(self, vk: int) -> None:
        mod_flag = _MODIFIER_VK_TO_FLAG.get(vk)
        if mod_flag:
            self._current_modifiers |= mod_flag

        if vk in self._pressed_keys:
            return
        self._pressed_keys.add(vk)

        with self._lock:
            callback = self._hooks.get((self._current_modifiers, vk))

        if callback is not None:
            try:
                callback()
            except Exception:
                logger.exception("Error in low-level keyboard hook callback")

    def _on_key_up(self, vk: int) -> None:
        mod_flag = _MODIFIER_VK_TO_FLAG.get(vk)
        if mod_flag:
            other_vk_pressed = False
            for other_vk, other_flag in _MODIFIER_VK_TO_FLAG.items():
                if other_vk != vk and other_flag == mod_flag and other_vk in self._pressed_keys:
                    other_vk_pressed = True
                    break
            if not other_vk_pressed:
                self._current_modifiers &= ~mod_flag

        self._pressed_keys.discard(vk)
