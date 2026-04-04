from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .history import HistoryStore
from .loader import load_script_processor
from .models import ClipboardEvent
from .watcher import ClipboardWatcher


@dataclass(slots=True)
class PlatexApp:
    db_path: Path | None
    script_path: Path
    interval: float = 0.8
    isolate_mode: bool = False
    restore_delay: float = 0.25
    on_ocr_success: Callable[[ClipboardEvent], None] | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _worker: threading.Thread | None = field(default=None, init=False, repr=False)
    _watcher: ClipboardWatcher | None = field(default=None, init=False, repr=False)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("platex.app"), init=False, repr=False)

    def _ensure_watcher(self) -> ClipboardWatcher:
        if self._watcher is None:
            history = HistoryStore(self.db_path)
            processor = load_script_processor(self.script_path)
            self._watcher = ClipboardWatcher(
                processor=processor,
                history=history,
                source_name=str(self.script_path),
            )
        return self._watcher

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return

        self.logger.info("Starting background watcher script=%s interval=%s", self.script_path, self.interval)

        if self.isolate_mode:
            self._ensure_watcher()
            self.logger.info("Isolation mode enabled: background polling is disabled")
            return

        watcher = self._ensure_watcher()

        def run() -> None:
            while not self._stop_event.is_set():
                try:
                    event = watcher.poll_once()
                    if event is not None and event.status == "ok" and self.on_ocr_success is not None:
                        self.on_ocr_success(event)
                except Exception as exc:  # noqa: BLE001
                    self.logger.exception("Error in clipboard poll loop: %s", exc)
                self._stop_event.wait(self.interval)

        self._worker = threading.Thread(target=run, name="platex-watcher", daemon=True)
        self._worker.start()

    def run_once(self):
        watcher = self._ensure_watcher()
        event = watcher.poll_once()
        if event is not None and event.status == "ok" and self.on_ocr_success is not None:
            self.on_ocr_success(event)
        return event

    def stop(self) -> None:
        self.logger.info("Stopping background watcher")
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
