from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from collections.abc import Callable

from .clipboard import grab_image_clipboard, image_hash
from .history import HistoryStore
from .models import ClipboardEvent, OcrProcessor


@dataclass(slots=True)
class ClipboardWatcher:
    processor: OcrProcessor
    history: HistoryStore
    source_name: str
    on_success: Callable[[str], None] | None = None
    last_image_hash: str | None = None
    last_image_time: float | None = None
    last_publish_time: float | None = None
    ocr_start_time: float | None = None
    _processing_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _publishing: bool = field(default=False, init=False, repr=False)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("platex.watcher"), init=False, repr=False)

    def set_publishing(self, is_publishing: bool) -> None:
        self._publishing = is_publishing

    def poll_once(self) -> ClipboardEvent | None:
        # Skip processing if currently publishing to clipboard
        if self._publishing:
            self.logger.debug("Skipping poll during clipboard publish/restore")
            return None

        # Skip if OCR is still processing previous image (prevent queuing during long OCR operations)
        if self.ocr_start_time is not None:
            ocr_elapsed = time.time() - self.ocr_start_time
            if ocr_elapsed < 15.0:  # Typical OCR takes 8-12 seconds, allow up to 15s
                self.logger.debug("Skipping poll during OCR processing (%.1fs elapsed)", ocr_elapsed)
                return None
            else:
                # OCR took too long, assume it crashed and reset the flag
                self.ocr_start_time = None

        with self._processing_lock:
            image = grab_image_clipboard()
            if image is None:
                self.logger.debug("Clipboard poll found no image content")
                return None

            current_hash = image_hash(image.image_bytes)
            current_time = time.time()
            
            # Skip if same hash detected within 3 seconds (likely clipboard restore echo)
            if current_hash == self.last_image_hash and self.last_image_time is not None:
                time_delta = current_time - self.last_image_time
                if time_delta < 3.0:
                    self.logger.debug("Skipping duplicate clipboard image echo: %s (%.1fs ago)", current_hash[:10], time_delta)
                    return None

            # Skip if recent publish operation (within 1.5 seconds) to avoid restoring image being processed
            if self.last_publish_time is not None:
                time_since_publish = current_time - self.last_publish_time
                if time_since_publish < 1.5:
                    self.logger.debug("Skipping image within %.1fs of publish (likely restore)", time_since_publish)
                    return None

            self.last_image_hash = current_hash
            self.last_image_time = current_time
        
        # Release lock before expensive OCR operation
        now = datetime.now(timezone.utc)
        self.ocr_start_time = time.time()  # Mark OCR as started
        self.logger.info("OCR start hash=%s size=%sx%s source=%s", current_hash[:10], image.width, image.height, self.source_name)

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
            self.ocr_start_time = None  # Mark OCR as completed

        self.history.add(event)
        if event.status == "ok" and self.on_success is not None:
            self.logger.info("Publishing LaTeX to clipboard hash=%s latex_len=%s", current_hash[:10], len(event.latex))
            self.last_publish_time = time.time()  # Record publish time to skip restore echoes
            self.on_success(event.latex)
        return event