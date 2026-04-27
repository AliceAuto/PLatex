from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .app_state import AppState, StateMachine
from .events import EventBus, OcrSuccessEvent, get_event_bus
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
    _watcher_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _run_once_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _state_machine: StateMachine = field(default_factory=StateMachine, init=False, repr=False)
    _bus: EventBus = field(default_factory=get_event_bus, init=False, repr=False)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("platex.app"), init=False, repr=False)
    registry: ScriptRegistry = field(default_factory=ScriptRegistry, init=False, repr=False)
    hotkey_listener: HotkeyListener = field(default_factory=HotkeyListener, init=False, repr=False)
    _external_history: HistoryStore | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self._bus.subscribe(OcrSuccessEvent, self._on_ocr_success_event)

    def _on_ocr_success_event(self, event: OcrSuccessEvent) -> None:
        if self.on_ocr_success is None:
            return
        clipboard_event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash=event.image_hash,
            image_width=event.image_width,
            image_height=event.image_height,
            latex=event.latex,
            source=event.source,
            status="ok",
            error=None,
        )
        self.on_ocr_success(clipboard_event)

    @property
    def state(self) -> AppState:
        return self._state_machine.state

    @property
    def is_running(self) -> bool:
        return self._state_machine.is_running

    def set_external_history(self, history: HistoryStore) -> None:
        self._external_history = history

    def _ensure_watcher(self) -> ClipboardWatcher:
        if self._watcher is not None:
            return self._watcher
        with self._watcher_lock:
            if self._watcher is not None:
                return self._watcher
            history = self._external_history or HistoryStore(self.db_path)
            processor = load_script_processor(self.script_path)
            self._watcher = ClipboardWatcher(
                processor=processor,
                history=history,
                source_name=str(self.script_path),
            )
            return self._watcher

    def start(self, script_configs: dict[str, dict[str, Any]] | None = None) -> None:
        if not self._state_machine.transition_to(AppState.STARTING):
            if self._state_machine.state == AppState.RUNNING:
                return
            self._state_machine.force_state(AppState.STARTING)

        self._stop_event.clear()

        self.logger.info("Starting background watcher script=%s interval=%s", self.script_path, self.interval)

        try:
            self._start_registry()
            if script_configs:
                self.registry.load_configs(script_configs)
            self._start_hotkeys()
        except Exception:
            self.logger.exception("Error during startup, forcing stop")
            self._state_machine.force_state(AppState.STOPPED)
            return

        if self.isolate_mode:
            try:
                self._ensure_watcher()
            except Exception:
                self.logger.exception("Error creating watcher in isolate mode")
                self._state_machine.force_state(AppState.STOPPED)
                return
            self._state_machine.transition_to(AppState.RUNNING)
            self.logger.info("Isolation mode enabled: background polling is disabled")
            return

        try:
            watcher = self._ensure_watcher()
        except Exception:
            self.logger.exception("Error creating watcher")
            self._state_machine.force_state(AppState.STOPPED)
            return

        def run() -> None:
            consecutive_errors = 0
            max_consecutive_errors = 50
            while not self._stop_event.is_set():
                try:
                    event = watcher.poll_once()
                    consecutive_errors = 0
                    if event is not None and event.status == "ok" and self.on_ocr_success is not None:
                        try:
                            self.on_ocr_success(event)
                        except Exception:
                            self.logger.exception("Error in OCR success callback")
                except Exception as exc:
                    consecutive_errors += 1
                    self.logger.exception("Error in clipboard poll loop: %s", exc)
                    if consecutive_errors >= max_consecutive_errors:
                        self.logger.critical("Too many consecutive errors (%d), stopping watcher", consecutive_errors)
                        self._state_machine.force_state(AppState.STOPPED)
                        break
                wait_time = max(self.interval, 0.1)
                if consecutive_errors > 2:
                    backoff = min(consecutive_errors * 0.5, 10.0)
                    wait_time += backoff
                self._stop_event.wait(wait_time)

        self._worker = threading.Thread(target=run, name="platex-watcher", daemon=True)
        self._worker.start()
        self._state_machine.transition_to(AppState.RUNNING)

    def _start_registry(self) -> None:
        scripts_dir = default_scripts_dir()

        primary_dir = self.script_path.parent
        if primary_dir.is_dir() and primary_dir != scripts_dir:
            self.registry.discover_scripts(primary_dir)

        if scripts_dir.is_dir():
            self.registry.discover_scripts(scripts_dir)

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
        self.logger.info("Starting hotkey registration")
        all_bindings: dict[str, Callable[[], None]] = {}
        for entry in self.registry.get_hotkey_scripts():
            try:
                bindings = entry.script.get_hotkey_bindings()
            except Exception as exc:
                self.logger.exception("Failed to get hotkey bindings from %s: %s", entry.script.name, exc)
                continue
            for hotkey, action in bindings.items():
                script_ref = entry.script

                def _make_cb(s: object, a: str, log: logging.Logger) -> Callable[[], None]:
                    def _cb() -> None:
                        try:
                            s.on_hotkey(a)
                        except Exception:
                            log.exception("Error in hotkey callback for %s", a)
                    return _cb

                all_bindings[hotkey] = _make_cb(script_ref, action, self.logger)

        self.logger.info("Starting hotkey listener")
        if all_bindings:
            self.hotkey_listener.register_many(all_bindings)
            for hotkey in all_bindings:
                self.logger.info("Registered hotkey: %s", hotkey)

        try:
            self.hotkey_listener.start()
            self.logger.info("Hotkey listener started successfully")
        except Exception as exc:
            self.logger.exception("Failed to start hotkey listener: %s", exc)

    def run_once(self):
        with self._run_once_lock:
            try:
                watcher = self._ensure_watcher()
                event = watcher.poll_once(force=True)
            except Exception:
                self.logger.exception("Error in run_once")
                return None
        if event is not None and event.status == "ok" and self.on_ocr_success is not None:
            try:
                self.on_ocr_success(event)
            except Exception:
                self.logger.exception("Error in OCR success callback")
        return event

    def stop(self) -> None:
        if not self._state_machine.can_transition_to(AppState.STOPPING):
            if self._state_machine.is_stopped:
                return
            self._state_machine.force_state(AppState.STOPPING)

        self._state_machine.transition_to(AppState.STOPPING)
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
            self._worker = None
        with self._watcher_lock:
            if self._watcher is not None:
                try:
                    if self._external_history is not None:
                        self._watcher.history = None
                    self._watcher.close()
                except Exception:
                    self.logger.debug("Error closing watcher during stop")
                self._watcher = None
        self._state_machine.transition_to(AppState.STOPPED)

    def apply_registry_hotkeys(self) -> None:
        self.hotkey_listener.clear()
        self._start_hotkeys()

    _restart_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)

    def restart_watcher(self, *, script_path: Path | None = None, interval: float | None = None, isolate_mode: bool | None = None) -> None:
        with self._restart_lock:
            was_running = self._state_machine.is_running
            try:
                self.stop()
            except Exception:
                self.logger.exception("Error stopping watcher during restart")
                self._state_machine.force_state(AppState.STOPPED)
                if self._worker is not None and self._worker.is_alive():
                    self._worker.join(timeout=5.0)
                    if self._worker.is_alive():
                        self.logger.error("Old worker thread still alive after restart stop, aborting restart")
                        return
                    self._worker = None
            finally:
                if script_path is not None:
                    self.script_path = script_path
                if interval is not None:
                    self.interval = interval
                if isolate_mode is not None:
                    self.isolate_mode = isolate_mode
                self._stop_event.clear()
            if was_running:
                self.start()
