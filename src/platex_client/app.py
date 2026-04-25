from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .history import HistoryStore
from .hotkey_listener import HotkeyListener
from .loader import load_script_processor
from .models import ClipboardEvent
from .script_registry import ScriptRegistry, default_scripts_dir
from .watcher import ClipboardWatcher


@dataclass(slots=True)
class PlatexApp:
    db_path: Path | None
    script_path: Path
    interval: float = 0.8
    isolate_mode: bool = False
    on_ocr_success: Callable[[ClipboardEvent], None] | None = None
    _stop_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _worker: threading.Thread | None = field(default=None, init=False, repr=False)
    _watcher: ClipboardWatcher | None = field(default=None, init=False, repr=False)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("platex.app"), init=False, repr=False)
    registry: ScriptRegistry = field(default_factory=ScriptRegistry, init=False, repr=False)
    hotkey_listener: HotkeyListener = field(default_factory=HotkeyListener, init=False, repr=False)

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

        self._start_registry()
        self._start_hotkeys()

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
                wait_time = max(self.interval, 0.1)
                self._stop_event.wait(wait_time)

        self._worker = threading.Thread(target=run, name="platex-watcher", daemon=True)
        self._worker.start()

    def _start_registry(self) -> None:
        scripts_dir = default_scripts_dir()

        # Also add the primary script_path directory
        primary_dir = self.script_path.parent
        if primary_dir.is_dir() and primary_dir != scripts_dir:
            self.registry.discover_scripts(primary_dir)

        if scripts_dir.is_dir():
            self.registry.discover_scripts(scripts_dir)

        # If the primary script_path isn't in a discovered directory, load it directly
        if self.script_path.exists():
            existing = self.registry.get(self.script_path.stem)
            if existing is None:
                self.registry.load_script_file(self.script_path)

        for entry in self.registry.get_all_scripts():
            if entry.enabled:
                try:
                    entry.script.activate()
                    self.logger.info("Activated script: %s", entry.script.name)
                except Exception as exc:
                    self.logger.exception("Failed to activate script %s: %s", entry.script.name, exc)

    def _start_hotkeys(self) -> None:
        for entry in self.registry.get_hotkey_scripts():
            try:
                bindings = entry.script.get_hotkey_bindings()
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("Failed to get hotkey bindings from %s: %s", entry.script.name, exc)
                continue
            for hotkey, action in bindings.items():
                script_ref = entry.script

                def _make_cb(s: object, a: str, log: logging.Logger) -> Callable[[], None]:
                    def _cb() -> None:
                        try:
                            s.on_hotkey(a)  # type: ignore[attr-defined]
                        except Exception:  # noqa: BLE001
                            log.exception("Error in hotkey callback for %s", a)
                    return _cb

                success = self.hotkey_listener.register(hotkey, _make_cb(script_ref, action, self.logger))
                if success:
                    self.logger.info("Registered hotkey: %s -> %s.%s", hotkey, entry.script.name, action)
                else:
                    self.logger.warning("Failed to register hotkey: %s -> %s.%s (may be in use by another application)", hotkey, entry.script.name, action)

        try:
            self.hotkey_listener.start()
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("Failed to start hotkey listener: %s", exc)

    def run_once(self):
        watcher = self._ensure_watcher()
        event = watcher.poll_once(force=True)
        if event is not None and event.status == "ok" and self.on_ocr_success is not None:
            self.on_ocr_success(event)
        return event

    def stop(self) -> None:
        self.logger.info("Stopping background watcher")
        self._stop_event.set()
        self.hotkey_listener.stop()
        for entry in self.registry.get_all_scripts():
            try:
                entry.script.deactivate()
            except Exception as exc:
                self.logger.debug("Failed to deactivate script %s: %s", entry.script.name, exc)
        if self._worker is not None:
            self._worker.join(timeout=2.0)

    def apply_registry_hotkeys(self) -> None:
        """Re-apply hotkey bindings after script config changes."""
        self.hotkey_listener.clear()
        self._start_hotkeys()