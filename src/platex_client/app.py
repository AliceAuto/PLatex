from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .app_state import AppState, StateMachine
from .events import EventBus, get_event_bus
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
        pass

    @property
    def state(self) -> AppState:
        return self._state_machine.state

    @property
    def is_running(self) -> bool:
        return self._state_machine.is_running

    def set_watcher_publishing(self, is_publishing: bool) -> None:
        with self._watcher_lock:
            if self._watcher is not None:
                self._watcher.set_publishing(is_publishing)

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
            for entry in self.registry.get_all_scripts():
                try:
                    entry.script.deactivate()
                except Exception:
                    self.logger.debug("Failed to deactivate script %s during rollback", entry.script.name)
            self._state_machine.force_state(AppState.STOPPED)
            return

        if self.isolate_mode:
            try:
                self._ensure_watcher()
            except Exception:
                self.logger.exception("Error creating watcher in isolate mode")
                self._cleanup_on_start_failure()
                return
            self._state_machine.transition_to(AppState.RUNNING)
            self.logger.info("Isolation mode enabled: background polling is disabled")
            return

        try:
            watcher = self._ensure_watcher()
        except Exception:
            self.logger.exception("Error creating watcher")
            self._cleanup_on_start_failure()
            return

        from .clipboard import set_publishing_callback

        def _on_publishing(is_publishing: bool) -> None:
            w = self._watcher
            if w is not None:
                try:
                    w.set_publishing(is_publishing)
                except Exception:
                    pass

        set_publishing_callback(_on_publishing)

        def run() -> None:
            consecutive_errors = 0
            max_consecutive_errors = 50

            def _on_ocr_result(event: ClipboardEvent | None) -> None:
                if event is not None and event.status == "ok" and self.on_ocr_success is not None:
                    try:
                        self.on_ocr_success(event)
                    except Exception:
                        self.logger.exception("Error in OCR success callback")

            while not self._stop_event.is_set():
                try:
                    watcher.poll_once_async(callback=_on_ocr_result)
                    consecutive_errors = 0
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

    def _cleanup_on_start_failure(self) -> None:
        try:
            self.hotkey_listener.stop()
        except Exception:
            self.logger.debug("Failed to stop hotkey listener during cleanup")
        for entry in self.registry.get_all_scripts():
            try:
                entry.script.deactivate()
            except Exception:
                self.logger.debug("Failed to deactivate script %s during cleanup", entry.script.name)
        self._state_machine.force_state(AppState.STOPPED)

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
        passthrough_bindings: dict[str, Callable[[], None]] = {}
        for entry in self.registry.get_hotkey_scripts():
            try:
                bindings = entry.script.get_hotkey_bindings()
            except Exception as exc:
                self.logger.exception("Failed to get hotkey bindings from %s: %s", entry.script.name, exc)
                continue
            self.logger.info("Script %s: passthrough=%s, bindings=%s, groups=%s",
                             entry.script.name,
                             getattr(entry.script, 'passthrough_hotkeys', False),
                             bindings,
                             getattr(entry.script, '_groups', 'N/A'))
            is_passthrough = getattr(entry.script, 'passthrough_hotkeys', False)
            for hotkey, action in bindings.items():
                script_ref = entry.script

                def _make_cb(s: object, a: str, log: logging.Logger) -> Callable[[], None]:
                    def _cb() -> None:
                        try:
                            s.on_hotkey(a)
                        except Exception:
                            log.exception("Error in hotkey callback for %s", a)
                    return _cb

                callback = _make_cb(script_ref, action, self.logger)
                if is_passthrough:
                    passthrough_bindings[hotkey] = callback
                else:
                    all_bindings[hotkey] = callback

        self.logger.info("Starting hotkey listener")
        self.hotkey_listener.batch_begin()
        try:
            if all_bindings:
                self.hotkey_listener.register_many(all_bindings)
                for hotkey in all_bindings:
                    self.logger.info("Registered hotkey: %s", hotkey)

            for hotkey, callback in passthrough_bindings.items():
                self.hotkey_listener.register_passthrough(hotkey, callback)
                self.logger.info("Registered passthrough hotkey: %s", hotkey)

            try:
                self.hotkey_listener.start()
                self.logger.info("Hotkey listener started successfully")
            except Exception as exc:
                self.logger.exception("Failed to start hotkey listener: %s", exc)
        finally:
            self.hotkey_listener.batch_end()

    def run_once(self):
        result_event = threading.Event()
        result_holder: list[ClipboardEvent | None] = [None]

        def _on_done(event: ClipboardEvent | None) -> None:
            result_holder[0] = event
            result_event.set()
            if event is not None and event.status == "ok" and self.on_ocr_success is not None:
                try:
                    self.on_ocr_success(event)
                except Exception:
                    self.logger.exception("Error in OCR success callback")

        try:
            watcher = self._ensure_watcher()
            started = watcher.poll_once_async(_on_done, force=True)
        except Exception:
            self.logger.exception("Error in run_once")
            return None

        if not started:
            return None

        if not result_event.wait(timeout=30.0):
            self.logger.warning("run_once timed out after 30s, OCR continues in background")
            return None

        return result_holder[0]

    def run_once_async(self, callback: Callable[[ClipboardEvent | None], None] | None = None) -> bool:
        try:
            watcher = self._ensure_watcher()
        except Exception:
            self.logger.exception("Error in run_once_async")
            if callback is not None:
                try:
                    callback(None)
                except Exception:
                    pass
            return False

        def _on_ocr_done(event: ClipboardEvent | None) -> None:
            if event is not None and event.status == "ok" and self.on_ocr_success is not None:
                try:
                    self.on_ocr_success(event)
                except Exception:
                    self.logger.exception("Error in OCR success callback")
            if callback is not None:
                try:
                    callback(event)
                except Exception:
                    self.logger.exception("Error in run_once_async callback")

        try:
            return watcher.poll_once_async(_on_ocr_done, force=True)
        except Exception:
            self.logger.exception("Error starting async OCR")
            if callback is not None:
                try:
                    callback(None)
                except Exception:
                    pass
            return False

    def stop(self) -> None:
        if not self._state_machine.can_transition_to(AppState.STOPPING):
            if self._state_machine.is_stopped:
                return
            self._state_machine.force_state(AppState.STOPPING)

        self._state_machine.transition_to(AppState.STOPPING)
        self.logger.info("Stopping background watcher")
        self._stop_event.set()
        try:
            from .clipboard import set_publishing_callback
            set_publishing_callback(None)
        except Exception:
            pass
        try:
            self.hotkey_listener.stop()
        except Exception:
            self.logger.debug("Error stopping hotkey listener during shutdown", exc_info=True)
        for entry in self.registry.get_all_scripts():
            try:
                entry.script.deactivate()
            except Exception as exc:
                self.logger.debug("Failed to deactivate script %s: %s", entry.script.name, exc)
        worker = self._worker
        if self._worker is not None:
            self._worker.join(timeout=2.0)
            if self._worker.is_alive():
                self.logger.warning("Worker thread still alive after 2s join, waiting longer...")
                self._worker.join(timeout=3.0)
                if self._worker.is_alive():
                    self.logger.error(
                        "Worker thread still alive after extended wait (daemon=True, will be killed on exit)"
                    )
            self._worker = None
        with self._watcher_lock:
            watcher = self._watcher
            if watcher is not None:
                try:
                    if self._external_history is not None:
                        watcher.history = None
                    watcher.close()
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
            saved_configs = self.registry.save_configs()
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

            if script_path is not None:
                self.script_path = script_path
            if interval is not None:
                clamped = max(0.1, min(60.0, interval))
                if clamped != interval:
                    if interval < 0.1:
                        self.logger.warning("Interval %.3f is too small, clamping to %.1f", interval, clamped)
                    else:
                        self.logger.warning("Interval %.3f is too large, clamping to %.1f", interval, clamped)
                self.interval = clamped
            if isolate_mode is not None:
                self.isolate_mode = isolate_mode
            self.registry.clear()
            self._stop_event.clear()
            with self._watcher_lock:
                if self._watcher is not None:
                    try:
                        self._watcher.close()
                    except Exception:
                        self.logger.debug("Error closing old watcher during restart")
                    self._watcher = None
            if was_running:
                try:
                    self.start(script_configs=saved_configs)
                except Exception:
                    self.logger.exception("Error starting watcher during restart")
