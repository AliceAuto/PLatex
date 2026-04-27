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
    def __init__(self) -> None:
        self._subscribers: dict[type[Event], list[Callable[[Event], None]]] = defaultdict(list)
        self._weak_subscribers: dict[type[Event], list[weakref.ref[Callable[[Event], None]]]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, event_type: type[Event], callback: Callable[[Event], None]) -> None:
        with self._lock:
            self._subscribers[event_type].append(callback)

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
            self._subscribers[event_type] = [cb for cb in subs if cb is not callback]
            weak_subs = self._weak_subscribers.get(event_type, [])
            self._weak_subscribers[event_type] = [ref for ref in weak_subs if ref() is not None and ref() is not callback]

    def unsubscribe_all(self, event_type: type[Event] | None = None) -> None:
        with self._lock:
            if event_type is None:
                self._subscribers.clear()
                self._weak_subscribers.clear()
            else:
                self._subscribers.pop(event_type, None)
                self._weak_subscribers.pop(event_type, None)

    def emit(self, event: Event) -> None:
        event_type = type(event)
        with self._lock:
            strong_cbs = list(self._subscribers.get(event_type, []))
            weak_refs = list(self._weak_subscribers.get(event_type, []))

        dead_refs: set[weakref.ref[Callable[[Event], None]]] = set()

        for cb in strong_cbs:
            try:
                cb(event)
            except Exception:
                logger.exception("Error in EventBus subscriber for %s", event_type.__name__)

        for ref in weak_refs:
            cb = ref()
            if cb is not None:
                try:
                    cb(event)
                except Exception:
                    logger.exception("Error in EventBus weak subscriber for %s", event_type.__name__)
            else:
                dead_refs.add(ref)

        if dead_refs:
            with self._lock:
                current = self._weak_subscribers.get(event_type, [])
                alive = [r for r in current if r not in dead_refs]
                self._weak_subscribers[event_type] = alive

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()
            self._weak_subscribers.clear()


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
