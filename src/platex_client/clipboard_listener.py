from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import Any

from .platform_utils import IS_WINDOWS, KERNEL32, USER32, make_wndclass_type
from .win32_utils import register_window_class, create_message_window, destroy_message_window

logger = logging.getLogger("platex.clipboard_listener")

_WM_CLIPBOARDUPDATE = 0x031D
_WM_DESTROY = 0x0002
_WM_USER_STOP = 0x0401


_instance_counter = 0
_instance_lock = threading.Lock()


class ClipboardChangeListener:
    def __init__(self) -> None:
        global _instance_counter
        with _instance_lock:
            _instance_counter += 1
            self._instance_id = _instance_counter
        self._change_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._hwnd: int = 0
        self._hwnd_lock = threading.Lock()
        self._thread_id: int = 0
        self._wnd_proc_cb: Any = None
        self._WNDPROC_TYPE: Any = None
        self._init_success = threading.Event()
        self._init_failed = threading.Event()
        self._start_lock = threading.Lock()

    @property
    def change_event(self) -> threading.Event:
        return self._change_event

    def start(self) -> bool:
        if not IS_WINDOWS or USER32 is None:
            logger.debug("Clipboard listener not available (non-Windows)")
            return False

        with self._start_lock:
            if self._init_success.is_set():
                return True

            self._stop_event.clear()
            self._change_event.clear()
            self._init_success.clear()
            self._init_failed.clear()
            self._thread = threading.Thread(target=self._message_loop, name="platex-clipboard-listener", daemon=True)
            self._thread.start()

        if self._init_failed.wait(timeout=2.0):
            logger.warning("Clipboard listener initialization failed")
            return False

        if not self._init_success.is_set():
            logger.warning("Clipboard listener thread did not start in time")
            return False

        logger.info("Clipboard change listener started")
        return True

    def stop(self) -> None:
        if self._stop_event.is_set() and self._thread is None:
            return
        self._stop_event.set()
        with self._hwnd_lock:
            hwnd = self._hwnd
            self._hwnd = 0
        if hwnd and USER32 is not None:
            try:
                USER32.PostMessageW(hwnd, _WM_USER_STOP, 0, 0)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._init_success.clear()
        self._init_failed.clear()
        logger.debug("Clipboard change listener stopped")

    def wait_for_change(self, timeout: float = 1.0) -> bool:
        result = self._change_event.wait(timeout=timeout)
        if result:
            self._change_event.clear()
        return result

    def _message_loop(self) -> None:
        if USER32 is None or KERNEL32 is None:
            self._init_failed.set()
            return

        self._thread_id = KERNEL32.GetCurrentThreadId()

        self._WNDPROC_TYPE = ctypes.WINFUNCTYPE(
            ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
            ctypes.c_ssize_t, ctypes.c_ssize_t,
        )
        self._wnd_proc_cb = self._WNDPROC_TYPE(self._wnd_proc)
        WNDPROC = self._WNDPROC_TYPE

        hinst = KERNEL32.GetModuleHandleW(None)
        class_name = f"PLatexClipListener_{self._instance_id}"

        if not register_window_class(class_name, self._wnd_proc_cb, WNDPROC, hinst):
            self._init_failed.set()
            return

        msg_hwnd = create_message_window(class_name, "PLatex Clipboard Listener", hinst)

        if not msg_hwnd:
            destroy_message_window(0, class_name, hinst)
            self._init_failed.set()
            return

        with self._hwnd_lock:
            self._hwnd = msg_hwnd

        _AddClipboardFormatListener = getattr(USER32, "AddClipboardFormatListener", None)
        _RemoveClipboardFormatListener = getattr(USER32, "RemoveClipboardFormatListener", None)
        if _AddClipboardFormatListener is None:
            logger.warning("AddClipboardFormatListener not available on this system")
            destroy_message_window(msg_hwnd, class_name, hinst)
            with self._hwnd_lock:
                self._hwnd = 0
            self._init_failed.set()
            return

        _AddClipboardFormatListener.restype = wintypes.BOOL
        _AddClipboardFormatListener.argtypes = [wintypes.HWND]

        if _RemoveClipboardFormatListener is not None:
            _RemoveClipboardFormatListener.restype = wintypes.BOOL
            _RemoveClipboardFormatListener.argtypes = [wintypes.HWND]

        try:
            if not _AddClipboardFormatListener(msg_hwnd):
                err = ctypes.get_last_error()
                logger.warning("AddClipboardFormatListener failed: error %d", err)
                destroy_message_window(msg_hwnd, class_name, hinst)
                with self._hwnd_lock:
                    self._hwnd = 0
                self._init_failed.set()
                return
        except Exception as exc:
            logger.warning("AddClipboardFormatListener failed: %s", exc)
            destroy_message_window(msg_hwnd, class_name, hinst)
            with self._hwnd_lock:
                self._hwnd = 0
            self._init_failed.set()
            return

        self._init_success.set()
        logger.info("Clipboard listener window created hwnd=%s", msg_hwnd)

        msg = wintypes.MSG()
        try:
            while not self._stop_event.is_set():
                try:
                    ret = USER32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                except Exception:
                    logger.exception("GetMessageW raised unexpected exception in clipboard listener")
                    break
                if ret == -1:
                    err = ctypes.get_last_error()
                    logger.error("GetMessageW returned -1 in clipboard listener (error %d)", err)
                    break
                if ret == 0:
                    break
                try:
                    USER32.TranslateMessage(ctypes.byref(msg))
                    USER32.DispatchMessageW(ctypes.byref(msg))
                except Exception:
                    logger.exception("Error dispatching clipboard listener message")
        except Exception:
            logger.exception("Unexpected error in clipboard listener message loop")
        finally:
            try:
                if _RemoveClipboardFormatListener is not None and msg_hwnd:
                    _RemoveClipboardFormatListener(msg_hwnd)
            except Exception:
                pass
            destroy_message_window(msg_hwnd, class_name, hinst)
            with self._hwnd_lock:
                self._hwnd = 0
            self._wnd_proc_cb = None
            self._WNDPROC_TYPE = None
            self._init_success.clear()

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == _WM_CLIPBOARDUPDATE:
                self._change_event.set()
                return 0

            if msg == _WM_USER_STOP:
                USER32.PostQuitMessage(0)
                return 0

            if msg == _WM_DESTROY:
                USER32.PostQuitMessage(0)
                return 0
        except Exception:
            logger.debug("Error in _wnd_proc for msg=0x%X", msg)

        try:
            return USER32.DefWindowProcW(hwnd, msg, wparam, lparam)
        except Exception:
            return 0
