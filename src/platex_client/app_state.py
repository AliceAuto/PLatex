from __future__ import annotations

import logging
import threading
from enum import Enum, auto
from typing import Callable

from .events import AppStateChangedEvent, EventBus, get_event_bus

logger = logging.getLogger("platex.state")


class AppState(Enum):
    IDLE = auto()
    STARTING = auto()
    RUNNING = auto()
    PAUSED = auto()
    STOPPING = auto()
    STOPPED = auto()


_VALID_TRANSITIONS: dict[AppState, set[AppState]] = {
    AppState.IDLE: {AppState.STARTING},
    AppState.STARTING: {AppState.RUNNING, AppState.STOPPED},
    AppState.RUNNING: {AppState.PAUSED, AppState.STOPPING},
    AppState.PAUSED: {AppState.RUNNING, AppState.STOPPING},
    AppState.STOPPING: {AppState.STOPPED, AppState.IDLE},
    AppState.STOPPED: {AppState.IDLE, AppState.STARTING},
}


class StateMachine:
    def __init__(self, bus: EventBus | None = None) -> None:
        self._state = AppState.IDLE
        self._lock = threading.Lock()
        self._bus = bus or get_event_bus()
        self._on_transition: list[Callable[[AppState, AppState], None]] = []

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == AppState.RUNNING

    @property
    def is_stopped(self) -> bool:
        return self._state in {AppState.STOPPED, AppState.IDLE}

    def transition_to(self, new_state: AppState) -> bool:
        with self._lock:
            old_state = self._state
            if new_state not in _VALID_TRANSITIONS.get(old_state, set()):
                logger.warning("Invalid state transition: %s -> %s", old_state.name, new_state.name)
                return False
            self._state = new_state
            callbacks = list(self._on_transition)
            logger.info("State transition: %s -> %s", old_state.name, new_state.name)

        self._bus.emit(AppStateChangedEvent(old_state=old_state.name, new_state=new_state.name))

        for cb in callbacks:
            try:
                cb(old_state, new_state)
            except Exception:
                logger.exception("Error in state transition callback")

        return True

    def on_transition(self, callback: Callable[[AppState, AppState], None]) -> None:
        self._on_transition.append(callback)

    def can_transition_to(self, new_state: AppState) -> bool:
        with self._lock:
            return new_state in _VALID_TRANSITIONS.get(self._state, set())

    def force_state(self, state: AppState) -> None:
        with self._lock:
            old_state = self._state
            self._state = state
            callbacks = list(self._on_transition)
        logger.warning("Force state: %s -> %s", old_state.name, state.name)
        self._bus.emit(AppStateChangedEvent(old_state=old_state.name, new_state=state.name))

        for cb in callbacks:
            try:
                cb(old_state, state)
            except Exception:
                logger.exception("Error in state transition callback")
