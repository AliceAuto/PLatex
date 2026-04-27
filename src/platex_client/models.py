from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO
from typing import Any


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
    fingerprint: str = ""
    _pil_image: Any = field(default=None, repr=False)

    def get_pil_image(self) -> Any:
        from PIL import Image

        if self._pil_image is not None:
            return self._pil_image
        return Image.open(BytesIO(self.image_bytes))


class OcrProcessor:
    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        raise NotImplementedError