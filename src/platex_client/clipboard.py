from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from typing import Any
import logging
import time

from PIL import Image, ImageGrab

from .windows_clipboard import _clipboard_lock, _set_text_tkinter, set_text
from .models import ClipboardImage


logger = logging.getLogger("platex.clipboard")


def grab_image_clipboard() -> ClipboardImage | None:
    """Grab image from clipboard with retry logic for lock contention."""
    max_retries = 8
    for attempt in range(1, max_retries + 1):
        try:
            with _clipboard_lock:
                content: Any = ImageGrab.grabclipboard()
            if not isinstance(content, Image.Image):
                return None

            buffer = BytesIO()
            content.save(buffer, format="PNG")
            return ClipboardImage(image_bytes=buffer.getvalue(), width=content.width, height=content.height)
        except OSError as exc:
            if attempt < max_retries:
                logger.debug("Clipboard read attempt %s/%s failed: %s", attempt, max_retries, exc)
                time.sleep(0.12 * attempt)
                continue
            logger.debug("Clipboard read failed after retries: %s", exc)
            return None


def image_hash(image_bytes: bytes) -> str:
    return sha256(image_bytes).hexdigest()


def copy_text_to_clipboard(text: str) -> None:
    set_text(text)


def copy_text_to_clipboard_fast(text: str) -> None:
    """Write text to the clipboard with a single best-effort attempt."""
    try:
        with _clipboard_lock:
            _set_text_tkinter(text)
    except Exception:
        # Fall back to the verified path if the fast tkinter path fails.
        set_text(text)