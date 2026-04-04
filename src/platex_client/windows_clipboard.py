from __future__ import annotations

from contextlib import contextmanager
import ctypes
import logging
import threading
import time

logger = logging.getLogger("platex.clipboard")


_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_clipboard_lock = threading.Lock()


@contextmanager
def _open_clipboard():
    if not _user32.OpenClipboard(None):
        raise RuntimeError("Unable to open Windows clipboard")
    try:
        yield
    finally:
        _user32.CloseClipboard()


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


def _set_text_tkinter(text: str) -> None:
    """Set text to Windows clipboard using tkinter (most reliable pure-Python method)."""
    import tkinter as tk
    
    root = tk.Tk()
    root.withdraw()  # Hide the window
    
    try:
        root.clipboard_clear()
        root.update()  # Process pending events
        time.sleep(0.05)  # Wait for clipboard lock release
        
        root.clipboard_append(text)
        root.update()  # Ensure clipboard operation is processed
        time.sleep(0.15)  # Give Windows time to copy to system clipboard
        
        logger.info("tkinter Set-Clipboard succeeded")
    finally:
        try:
            root.destroy()
        except:
            pass


def set_text(text: str) -> None:
    try:
        encoded = text.encode("utf-16-le") + b"\x00\x00"
        handle = _allocate_global_memory(encoded)

        with _clipboard_lock:
            with _open_clipboard():
                _user32.EmptyClipboard()
                if not _user32.SetClipboardData(_CF_UNICODETEXT, handle):
                    _kernel32.GlobalFree(handle)
                    raise RuntimeError("Unable to write text to Windows clipboard")
    except Exception as exc:
        logger.warning("ctypes clipboard write failed, falling back to tkinter: %s", exc)
        _set_text_tkinter(text)


def publish_text_to_clipboard(text: str) -> None:
    """Publish LaTeX text to system clipboard (no image restoration)."""
    def worker() -> None:
        try:
            logger.debug("Publishing to clipboard: %s", text[:100].replace("\n", " "))
            set_text(text)
            logger.info("LaTeX published to clipboard top")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error during clipboard publish: %s", exc)

    threading.Thread(target=worker, name="platex-clipboard-publisher", daemon=True).start()
