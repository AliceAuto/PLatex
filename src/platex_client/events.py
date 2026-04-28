from __future__ import annotations

import logging
import threading
import weakref
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("platex.events")


@dataclass(frozen=True, slots=True)
class Event:
    pass


@dataclass(frozen=True, slots=True)
class OcrSuccessEvent(Event):
    image_hash: str = ""
    latex: str = ""
    image_width: int = 0
    image_height: int = 0
    source: str = ""


@dataclass(frozen=True, slots=True)
class OcrErrorEvent(Event):
    image_hash: str = ""
    error: str = ""
    source: str = ""


@dataclass(frozen=True, slots=True)
class AppStateChangedEvent(Event):
    old_state: str = ""
    new_state: str = ""


@dataclass(frozen=True, slots=True)
class ConfigChangedEvent(Event):
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HotkeyStatusChangedEvent(Event):
    status: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ClipboardPublishingEvent(Event):
    is_publishing: bool = False


@dataclass(frozen=True, slots=True)
class ShowPanelEvent(Event):
    pass


@dataclass(frozen=True, slots=True)
class ShutdownRequestEvent(Event):
    pass


class EventBus:
    _WEAK_REF_CLEANUP_THRESHOLD = 64

    def __init__(self) -> None:
        self._subscribers: dict[type[Event], list[Callable[[Event], None]]] = defaultdict(list)
        self._weak_subscribers: dict[type[Event], list[weakref.ref[Callable[[Event], None]]]] = defaultdict(list)
        self._lock = threading.RLock()
        self._emit_count: int = 0
        self._subscriber_refs: dict[type[Event], list[weakref.ref[Callable[[Event], None]]]] = defaultdict(list)

    def subscribe(self, event_type: type[Event], callback: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers[event_type].append(callback)
            try:
                if hasattr(callback, "__self__") and hasattr(callback, "__func__"):
                    ref = weakref.WeakMethod(callback, lambda r: self._remove_strong_callback(event_type, r))
                else:
                    ref = weakref.ref(callback, lambda r: self._remove_strong_callback(event_type, r))
                self._subscriber_refs[event_type].append(ref)
            except TypeError:
                pass

    def _remove_strong_callback(self, event_type: type[Event], dead_ref: weakref.ref[Callable[[Event], None]]) -> None:
        with self._lock:
            refs = self._subscriber_refs.get(event_type, [])
            dead_idx = None
            for i, r in enumerate(refs):
                if r is dead_ref:
                    dead_idx = i
                    break
            if dead_idx is not None:
                refs.pop(dead_idx)
                if dead_idx < len(self._subscribers.get(event_type, [])):
                    self._subscribers[event_type].pop(dead_idx)

    def subscribe_weak(self, event_type: type[Event], callback: Callable[[Event], None]) -> None:
        with self._lock:
            if hasattr(callback, "__self__") and hasattr(callback, "__func__"):
                ref = weakref.WeakMethod(callback)
            else:
                ref = weakref.ref(callback)
            self._weak_subscribers[event_type].append(ref)

    def unsubscribe(self, event_type: type[Event], callback: Callable[[Event], None]) -> None:
        with self._lock:
            subs = self._subscribers.get(event_type, [])
            remove_indices = [i for i, cb in enumerate(subs) if cb is callback]
            for i in reversed(remove_indices):
                self._subscribers[event_type].pop(i)
                if i < len(self._subscriber_refs.get(event_type, [])):
                    self._subscriber_refs[event_type].pop(i)
            weak_subs = self._weak_subscribers.get(event_type, [])
            self._weak_subscribers[event_type] = [
                ref for ref in weak_subs
                if ref() is not None and ref() is not callback
            ]

    def unsubscribe_all(self, event_type: type[Event] | None = None) -> None:
        with self._lock:
            if event_type is None:
                self._subscribers.clear()
                self._weak_subscribers.clear()
                self._subscriber_refs.clear()
            else:
                self._subscribers.pop(event_type, None)
                self._weak_subscribers.pop(event_type, None)
                self._subscriber_refs.pop(event_type, None)

    def emit(self, event: Event) -> None:
        event_type = type(event)
        with self._lock:
            strong_cbs = list(self._subscribers.get(event_type, []))
            weak_refs = list(self._weak_subscribers.get(event_type, []))
            self._emit_count += 1

        if self._emit_count % self._WEAK_REF_CLEANUP_THRESHOLD == 0:
            self._cleanup_all_dead_refs()

        dead_refs: list[weakref.ref[Callable[[Event], None]]] = []

        for cb in strong_cbs:
            try:
                cb(event)
            except Exception:
                logger.exception("Error in EventBus subscriber for %s", event_type.__name__)

        for ref in weak_refs:
            try:
                cb = ref()
            except Exception:
                dead_refs.append(ref)
                continue
            if cb is not None:
                try:
                    cb(event)
                except Exception:
                    logger.exception("Error in EventBus weak subscriber for %s", event_type.__name__)
            else:
                dead_refs.append(ref)

        if dead_refs:
            with self._lock:
                current = self._weak_subscribers.get(event_type, [])
                alive = [r for r in current if not any(r is dr for dr in dead_refs)]
                self._weak_subscribers[event_type] = alive

    def _cleanup_all_dead_refs(self) -> None:
        with self._lock:
            for event_type in list(self._weak_subscribers.keys()):
                current = self._weak_subscribers.get(event_type, [])
                alive = [r for r in current if r() is not None]
                if len(alive) < len(current):
                    self._weak_subscribers[event_type] = alive

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
            self._weak_subscribers.clear()
            self._subscriber_refs.clear()

    def subscriber_count(self, event_type: type[Event] | None = None) -> int:
        with self._lock:
            if event_type is None:
                return sum(len(v) for v in self._subscribers.values()) + sum(len(v) for v in self._weak_subscribers.values())
            return len(self._subscribers.get(event_type, [])) + len(self._weak_subscribers.get(event_type, []))


_global_bus: EventBus | None = None
_bus_lock = threading.Lock()


def get_event_bus() -> EventBus:
    global _global_bus
    if _global_bus is None:
        with _bus_lock:
            if _global_bus is None:
                _global_bus = EventBus()
    return _global_bus


def reset_event_bus() -> None:
    global _global_bus
    with _bus_lock:
        if _global_bus is not None:
            _global_bus.clear()
        _global_bus = None
