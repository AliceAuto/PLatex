from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class ClipboardEvent:
    created_at: datetime
    image_hash: str
    image_width: int
    image_height: int
    latex: str
    source: str
    status: str
    error: str | None = None


@dataclass(slots=True)
class ClipboardImage:
    image_bytes: bytes
    width: int
    height: int


class OcrProcessor:
    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        raise NotImplementedError