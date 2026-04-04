from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .clipboard import grab_image_clipboard, image_hash
from .history import HistoryStore
from .models import ClipboardEvent, OcrProcessor


@dataclass(slots=True)
class ClipboardWatcher:
    processor: OcrProcessor
    history: HistoryStore
    source_name: str
    last_image_hash: str | None = None

    def poll_once(self) -> ClipboardEvent | None:
        image = grab_image_clipboard()
        if image is None:
            return None

        current_hash = image_hash(image.image_bytes)
        if current_hash == self.last_image_hash:
            return None

        self.last_image_hash = current_hash
        now = datetime.now(timezone.utc)

        try:
            latex = self.processor.process_image(
                image.image_bytes,
                context={
                    "image_hash": current_hash,
                    "image_width": image.width,
                    "image_height": image.height,
                    "source": self.source_name,
                },
            )
            event = ClipboardEvent(
                created_at=now,
                image_hash=current_hash,
                image_width=image.width,
                image_height=image.height,
                latex=latex,
                source=self.source_name,
                status="ok",
                error=None,
            )
        except Exception as exc:  # noqa: BLE001
            event = ClipboardEvent(
                created_at=now,
                image_hash=current_hash,
                image_width=image.width,
                image_height=image.height,
                latex="",
                source=self.source_name,
                status="error",
                error=str(exc),
            )

        self.history.add(event)
        return event