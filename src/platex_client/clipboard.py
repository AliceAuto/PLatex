from __future__ import annotations

import logging
from collections.abc import Callable
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import time

from PIL import Image, ImageGrab

from .models import ClipboardImage
from .windows_clipboard import _clipboard_lock, _CLIPBOARD_LOCK_TIMEOUT, set_text

logger = logging.getLogger("platex.clipboard")

_MAX_IMAGE_SIZE = 20 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 16384

_publishing_callback: Callable[[bool], None] | None = None


def set_publishing_callback(callback: Callable[[bool], None] | None) -> None:
    global _publishing_callback
    _publishing_callback = callback


def grab_image_clipboard() -> ClipboardImage | None:
    """Grab image from clipboard with retry logic for lock contention."""
    max_retries = 8
    for attempt in range(1, max_retries + 1):
        try:
            if not _clipboard_lock.acquire(timeout=_CLIPBOARD_LOCK_TIMEOUT):
                logger.debug("Clipboard lock contention on attempt %s/%s, skipping", attempt, max_retries)
                return None
            try:
                content: Any = ImageGrab.grabclipboard()
            finally:
                _clipboard_lock.release()
            if isinstance(content, Image.Image):
                pass
            elif isinstance(content, list) and len(content) > 0:
                image = _try_load_image_from_file_list(content)
                if image is None:
                    return None
                content = image
            else:
                return None

            buffer = BytesIO()
            content.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
            if len(image_bytes) > _MAX_IMAGE_SIZE:
                logger.warning("Clipboard image too large (%d bytes), skipping", len(image_bytes))
                return None

            if content.width > _MAX_IMAGE_DIMENSION or content.height > _MAX_IMAGE_DIMENSION:
                logger.warning(
                    "Clipboard image dimensions too large (%dx%d, max %d), skipping",
                    content.width, content.height, _MAX_IMAGE_DIMENSION,
                )
                return None

            return ClipboardImage(image_bytes=image_bytes, width=content.width, height=content.height)
        except (OSError, ValueError, RuntimeError) as exc:
            if attempt < max_retries:
                logger.debug("Clipboard read attempt %s/%s failed: %s", attempt, max_retries, exc)
                time.sleep(0.12 * attempt)
                continue
            logger.debug("Clipboard read failed after retries: %s", exc)
            return None
        except Exception as exc:
            logger.exception("Unexpected error reading clipboard: %s", exc)
            return None


def _try_load_image_from_file_list(file_list: list) -> Image.Image | None:
    for item in file_list:
        if not isinstance(item, str):
            continue
        try:
            path = Path(item)
            if path.is_file() and path.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tiff", ".tif", ".webp"):
                img = Image.open(path)
                img.load()
                return img.convert("RGBA")
        except Exception:
            continue
    return None


def image_hash(image_bytes: bytes) -> str:
    return sha256(image_bytes).hexdigest()


def copy_text_to_clipboard(text: str) -> None:
    cb = _publishing_callback
    if cb is not None:
        try:
            cb(True)
        except Exception:
            pass
    try:
        set_text(text)
    except Exception as exc:
        logger.error("Failed to copy text to clipboard: %s", exc)
    finally:
        if cb is not None:
            try:
                cb(False)
            except Exception:
                pass