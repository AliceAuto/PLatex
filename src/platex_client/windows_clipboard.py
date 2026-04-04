from __future__ import annotations

from contextlib import contextmanager
import ctypes
import logging
import threading
import time

logger = logging.getLogger("platex.clipboard")


_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002

_MAX_CLIPBOARD_ATTEMPTS = 20
_CLIPBOARD_RETRY_DELAY_SECONDS = 0.08

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_clipboard_lock = threading.Lock()


@contextmanager
def _open_clipboard():
    last_error: Exception | None = None
    for attempt in range(1, _MAX_CLIPBOARD_ATTEMPTS + 1):
        if _user32.OpenClipboard(None):
            try:
                yield
            finally:
                _user32.CloseClipboard()
            return

        last_error = RuntimeError("Unable to open Windows clipboard")
        logger.debug(
            "OpenClipboard attempt %s/%s failed",
            attempt,
            _MAX_CLIPBOARD_ATTEMPTS,
        )
        time.sleep(_CLIPBOARD_RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError("Unable to open Windows clipboard after retries") from last_error


def _allocate_global_memory(data: bytes) -> int:
    handle = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
    if not handle:
        raise RuntimeError("Unable to allocate clipboard memory")

    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        _kernel32.GlobalFree(handle)
        raise RuntimeError("Unable to lock clipboard memory")

    try:
        ctypes.memmove(pointer, data, len(data))
    finally:
        _kernel32.GlobalUnlock(handle)

    return handle


def _set_text_ctypes(text: str) -> None:
    encoded = text.encode("utf-16-le") + b"\x00\x00"
    handle = _allocate_global_memory(encoded)

    with _clipboard_lock:
        with _open_clipboard():
            _user32.EmptyClipboard()
            if not _user32.SetClipboardData(_CF_UNICODETEXT, handle):
                _kernel32.GlobalFree(handle)
                raise RuntimeError("Unable to write text to Windows clipboard")


def _read_text_ctypes() -> str:
    with _clipboard_lock:
        with _open_clipboard():
            handle = _user32.GetClipboardData(_CF_UNICODETEXT)
            if not handle:
                raise RuntimeError("Unable to read text from Windows clipboard")

            pointer = _kernel32.GlobalLock(handle)
            if not pointer:
                raise RuntimeError("Unable to lock Windows clipboard text")

            try:
                return ctypes.wstring_at(pointer)
            finally:
                _kernel32.GlobalUnlock(handle)


def _set_text_tkinter(text: str) -> None:
    """Set text to Windows clipboard using tkinter (most reliable pure-Python method)."""
    import tkinter as tk
    
    root = tk.Tk()
    root.withdraw()  # Hide the window
    
    try:
        root.clipboard_clear()
        root.update()  # Process pending events
        time.sleep(0.01)  # Brief pause for clipboard state to settle
        
        root.clipboard_append(text)
        root.update()  # Ensure clipboard operation is processed
        time.sleep(0.03)  # Give Windows a small window to commit the data
        
        logger.info("tkinter Set-Clipboard succeeded")
    finally:
        try:
            root.destroy()
        except:
            pass


def _set_text_with_retry(text: str) -> None:
    last_error: Exception | None = None

    for attempt in range(1, _MAX_CLIPBOARD_ATTEMPTS + 1):
        try:
            _set_text_ctypes(text)
            verify_error: Exception | None = None
            for verify_attempt in range(1, _MAX_CLIPBOARD_ATTEMPTS + 1):
                try:
                    time.sleep(_CLIPBOARD_RETRY_DELAY_SECONDS * verify_attempt)
                    if _read_text_ctypes() == text:
                        return
                except Exception as exc:  # noqa: BLE001
                    verify_error = exc
                    continue
            raise RuntimeError("Clipboard verification failed after ctypes write") from verify_error
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.debug(
                "ctypes clipboard write attempt %s/%s failed: %s",
                attempt,
                _MAX_CLIPBOARD_ATTEMPTS,
                exc,
            )
            time.sleep(_CLIPBOARD_RETRY_DELAY_SECONDS * attempt)

    for attempt in range(1, _MAX_CLIPBOARD_ATTEMPTS + 1):
        try:
            _set_text_tkinter(text)
            verify_error: Exception | None = None
            for verify_attempt in range(1, _MAX_CLIPBOARD_ATTEMPTS + 1):
                try:
                    time.sleep(_CLIPBOARD_RETRY_DELAY_SECONDS * verify_attempt)
                    if _read_text_ctypes() == text:
                        return
                except Exception as exc:  # noqa: BLE001
                    verify_error = exc
                    continue
            raise RuntimeError("Clipboard verification failed after tkinter write") from verify_error
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            logger.debug(
                "tkinter clipboard write attempt %s/%s failed: %s",
                attempt,
                _MAX_CLIPBOARD_ATTEMPTS,
                exc,
            )
            time.sleep(_CLIPBOARD_RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError("Unable to write text to clipboard after retries") from last_error


def set_text(text: str) -> None:
    try:
        _set_text_with_retry(text)
    except Exception as exc:
        logger.exception("Unable to write text to Windows clipboard after retries: %s", exc)
        raise
