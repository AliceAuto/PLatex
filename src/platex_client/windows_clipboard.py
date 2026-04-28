from __future__ import annotations

import logging
import threading
import time

from .platform_utils import IS_WINDOWS, KERNEL32, USER32

logger = logging.getLogger("platex.clipboard")

_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002

_MAX_CLIPBOARD_ATTEMPTS = 10
_CLIPBOARD_RETRY_DELAY_SECONDS = 0.05
_MAX_VERIFY_ATTEMPTS = 3
_CLIPBOARD_TOTAL_TIMEOUT = 3.0
_CLIPBOARD_LOCK_TIMEOUT = 2.0

_clipboard_lock = threading.Lock()


def _try_open_clipboard() -> bool:
    if USER32 is None:
        return False
    return bool(USER32.OpenClipboard(None))


def _close_clipboard() -> None:
    if USER32 is not None:
        USER32.CloseClipboard()


def _allocate_global_memory(data: bytes) -> int:
    if KERNEL32 is None:
        raise RuntimeError("Clipboard API not available on this platform")

    handle = KERNEL32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
    if not handle:
        raise RuntimeError("Unable to allocate clipboard memory")

    pointer = KERNEL32.GlobalLock(handle)
    if not pointer:
        KERNEL32.GlobalFree(handle)
        raise RuntimeError("Unable to lock clipboard memory")

    try:
        import ctypes
        ctypes.memmove(pointer, data, len(data))
    finally:
        KERNEL32.GlobalUnlock(handle)

    return handle


def _set_text_ctypes(text: str) -> None:
    import ctypes

    encoded = text.encode("utf-16-le") + b"\x00\x00"
    handle = _allocate_global_memory(encoded)
    ownership_transferred = False

    try:
        for attempt in range(1, _MAX_CLIPBOARD_ATTEMPTS + 1):
            with _clipboard_lock:
                if _try_open_clipboard():
                    try:
                        USER32.EmptyClipboard()
                        if not USER32.SetClipboardData(_CF_UNICODETEXT, handle):
                            KERNEL32.GlobalFree(handle)
                            raise RuntimeError("Unable to write text to Windows clipboard")
                        ownership_transferred = True
                    finally:
                        _close_clipboard()
                    return
            if attempt < _MAX_CLIPBOARD_ATTEMPTS:
                time.sleep(_CLIPBOARD_RETRY_DELAY_SECONDS * attempt)
        raise RuntimeError("Unable to open Windows clipboard after retries")
    except Exception:
        if not ownership_transferred:
            KERNEL32.GlobalFree(handle)
        raise


def _read_text_ctypes() -> str:
    import ctypes

    for attempt in range(1, _MAX_CLIPBOARD_ATTEMPTS + 1):
        with _clipboard_lock:
            if _try_open_clipboard():
                try:
                    handle = USER32.GetClipboardData(_CF_UNICODETEXT)
                    if not handle:
                        raise RuntimeError("Unable to read text from Windows clipboard")

                    pointer = KERNEL32.GlobalLock(handle)
                    if not pointer:
                        raise RuntimeError("Unable to lock Windows clipboard text")

                    try:
                        return ctypes.wstring_at(pointer)
                    finally:
                        KERNEL32.GlobalUnlock(handle)
                finally:
                    _close_clipboard()
        if attempt < _MAX_CLIPBOARD_ATTEMPTS:
            time.sleep(_CLIPBOARD_RETRY_DELAY_SECONDS * attempt)
    raise RuntimeError("Unable to open Windows clipboard after retries")


def _set_text_with_retry(text: str) -> None:
    last_error: Exception | None = None
    deadline = time.monotonic() + _CLIPBOARD_TOTAL_TIMEOUT

    for attempt in range(1, _MAX_CLIPBOARD_ATTEMPTS + 1):
        if time.monotonic() >= deadline:
            break
        try:
            _set_text_ctypes(text)
            verify_error: Exception | None = None
            for verify_attempt in range(1, _MAX_VERIFY_ATTEMPTS + 1):
                if time.monotonic() >= deadline:
                    break
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

    raise RuntimeError("Unable to write text to clipboard after retries") from last_error


def set_text(text: str) -> None:
    if not IS_WINDOWS or USER32 is None:
        raise RuntimeError("Clipboard API not available on this platform")
    try:
        _set_text_with_retry(text)
    except Exception as exc:
        logger.exception("Unable to write text to Windows clipboard after retries: %s", exc)
        raise


def get_text() -> str | None:
    if not IS_WINDOWS or USER32 is None:
        return None
    try:
        return _read_text_ctypes()
    except Exception:
        return None
