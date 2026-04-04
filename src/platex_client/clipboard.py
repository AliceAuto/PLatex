from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from typing import Any

from PIL import Image, ImageGrab

from .models import ClipboardImage


def grab_image_clipboard() -> ClipboardImage | None:
    content: Any = ImageGrab.grabclipboard()
    if not isinstance(content, Image.Image):
        return None

    buffer = BytesIO()
    content.save(buffer, format="PNG")
    return ClipboardImage(image_bytes=buffer.getvalue(), width=content.width, height=content.height)


def image_hash(image_bytes: bytes) -> str:
    return sha256(image_bytes).hexdigest()


def copy_text_to_clipboard(text: str) -> None:
    import tkinter as tk

    root = tk.Tk()
    root.withdraw()
    root.clipboard_clear()
    root.clipboard_append(text)
    root.update()
    root.destroy()