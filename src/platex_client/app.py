from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from .history import HistoryStore
from .loader import load_script_processor
from .watcher import ClipboardWatcher


@dataclass(slots=True)
class PlatexApp:
    db_path: Path | None
    script_path: Path
    interval: float = 0.8
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _worker: threading.Thread | None = field(default=None, init=False, repr=False)

    def start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return

        history = HistoryStore(self.db_path)
        processor = load_script_processor(self.script_path)
        watcher = ClipboardWatcher(processor=processor, history=history, source_name=str(self.script_path))

        def run() -> None:
            while not self._stop_event.is_set():
                watcher.poll_once()
                self._stop_event.wait(self.interval)

        self._worker = threading.Thread(target=run, name="platex-watcher", daemon=True)
        self._worker.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._worker is not None:
            self._worker.join(timeout=2.0)
