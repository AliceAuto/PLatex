from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
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
    ocr_start_time: float | None = field(default=None, init=False, repr=False)
    _processing_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _publishing: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("platex.watcher"), init=False, repr=False)

    def __post_init__(self) -> None:
        self._publishing.set()

    def set_publishing(self, is_publishing: bool) -> None:
        if is_publishing:
            self._publishing.clear()
        else:
            self._publishing.set()

    def poll_once(self, *, force: bool = False) -> ClipboardEvent | None:
        if not self._publishing.is_set():
            self.logger.debug("Skipping poll during clipboard publish/restore")
            return None

        if self.ocr_start_time is not None:
            ocr_elapsed = time.time() - self.ocr_start_time
            if ocr_elapsed < 15.0:
                self.logger.debug("Skipping poll during OCR processing (%.1fs elapsed)", ocr_elapsed)
                return None
            else:
                self.ocr_start_time = None

        with self._processing_lock:
            image = grab_image_clipboard()
            if image is None:
                self.logger.debug("Clipboard poll found no image content")
                return None

            current_hash = image_hash(image.image_bytes)

            if not force and current_hash == self.last_image_hash:
                self.logger.debug("Skipping already processed clipboard image: %s", current_hash[:10])
                return None

            self.last_image_hash = current_hash

        now = datetime.now(timezone.utc)
        self.ocr_start_time = time.time()
        self.logger.info("OCR start hash=%s size=%dx%d source=%s", current_hash[:10], image.width, image.height, self.source_name)

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
            self.logger.info("OCR success hash=%s latex=%s", current_hash[:10], latex[:120].replace("\n", " "))
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("OCR failed hash=%s", current_hash[:10])
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
        finally:
            self.ocr_start_time = None

        try:
            self.history.add(event)
        except Exception as db_exc:
            self.logger.error("Failed to persist event to history: %s", db_exc)

        return event