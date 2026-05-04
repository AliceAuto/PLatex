from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.app_state import AppState, StateMachine
from platex_client.events import (
    AppStateChangedEvent,
    ClipboardPublishingEvent,
    ConfigChangedEvent,
    EventBus,
    Event,
    HotkeyStatusChangedEvent,
    OcrErrorEvent,
    OcrSuccessEvent,
    ShowPanelEvent,
    ShutdownRequestEvent,
    get_event_bus,
    reset_event_bus,
)
from platex_client.secrets import clear_all, set_secret


class TestEventFrozen(unittest.TestCase):
    def test_ocr_success_event_frozen(self):
        evt = OcrSuccessEvent(latex="x^2", image_hash="abc")
        with self.assertRaises(AttributeError):
            evt.latex = "y^2"

    def test_ocr_error_event_frozen(self):
        evt = OcrErrorEvent(error="fail", image_hash="abc")
        with self.assertRaises(AttributeError):
            evt.error = "new"

    def test_app_state_changed_event_frozen(self):
        evt = AppStateChangedEvent(old_state="IDLE", new_state="RUNNING")
        with self.assertRaises(AttributeError):
            evt.old_state = "STOPPED"

    def test_config_changed_event_frozen(self):
        evt = ConfigChangedEvent(payload={"key": "val"})
        with self.assertRaises(AttributeError):
            evt.payload = {}

    def test_hotkey_status_changed_event_frozen(self):
        evt = HotkeyStatusChangedEvent(status={"active": True})
        with self.assertRaises(AttributeError):
            evt.status = {}

    def test_clipboard_publishing_event_frozen(self):
        evt = ClipboardPublishingEvent(is_publishing=True)
        with self.assertRaises(AttributeError):
            evt.is_publishing = False

    def test_show_panel_event_frozen(self):
        evt = ShowPanelEvent()
        with self.assertRaises((AttributeError, TypeError)):
            evt.extra = "data"

    def test_shutdown_request_event_frozen(self):
        evt = ShutdownRequestEvent()
        with self.assertRaises((AttributeError, TypeError)):
            evt.extra = "data"


class TestEventBusSubscribeAndEmit(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_subscribe_and_emit_single(self):
        bus = EventBus()
        received = []
        bus.subscribe(OcrSuccessEvent, lambda e: received.append(e))
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].latex, "test")

    def test_multiple_subscribers_same_event(self):
        bus = EventBus()
        r1, r2 = [], []
        bus.subscribe(OcrSuccessEvent, lambda e: r1.append(e))
        bus.subscribe(OcrSuccessEvent, lambda e: r2.append(e))
        bus.emit(OcrSuccessEvent(latex="x"))
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)

    def test_different_event_types_isolated(self):
        bus = EventBus()
        r1, r2 = [], []
        bus.subscribe(OcrSuccessEvent, lambda e: r1.append(e))
        bus.subscribe(OcrErrorEvent, lambda e: r2.append(e))
        bus.emit(OcrSuccessEvent(latex="x"))
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 0)

    def test_emit_event_base_class_no_subscribers(self):
        bus = EventBus()
        bus.emit(Event())

    def test_unsubscribe_specific_callback(self):
        bus = EventBus()
        received = []
        cb = lambda e: received.append(e)
        bus.subscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="first"))
        bus.unsubscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="second"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].latex, "first")


class TestEventBusSubscriberCount(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_subscriber_count_empty(self):
        bus = EventBus()
        self.assertEqual(bus.subscriber_count(), 0)

    def test_subscriber_count_with_subscribers(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 1)

    def test_subscriber_count_total(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrErrorEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(), 2)

    def test_subscriber_count_with_weak(self):
        bus = EventBus()

        class Handler:
            def __call__(self, event):
                pass

        handler = Handler()
        bus.subscribe_weak(OcrSuccessEvent, handler)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 1)


class TestEventBusWeakSubscribe(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_weak_subscribe_receives_events(self):
        bus = EventBus()
        received = []

        class Handler:
            def __call__(self, event):
                received.append(event)

        handler = Handler()
        bus.subscribe_weak(OcrSuccessEvent, handler)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(received), 1)

    def test_weak_subscribe_method(self):
        bus = EventBus()
        received = []

        class Handler:
            def callback(self, event):
                received.append(event)

        handler = Handler()
        bus.subscribe_weak(OcrSuccessEvent, handler.callback)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(received), 1)


class TestEventBusClear(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_clear_removes_all(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrErrorEvent, lambda e: None)
        bus.clear()
        self.assertEqual(bus.subscriber_count(), 0)

    def test_clear_then_emit_no_error(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.clear()
        bus.emit(OcrSuccessEvent(latex="test"))


class TestEventBusUnsubscribeAll(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_unsubscribe_all_specific_type(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrErrorEvent, lambda e: None)
        bus.unsubscribe_all(OcrSuccessEvent)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 0)
        self.assertEqual(bus.subscriber_count(OcrErrorEvent), 1)

    def test_unsubscribe_all_types(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrErrorEvent, lambda e: None)
        bus.unsubscribe_all()
        self.assertEqual(bus.subscriber_count(), 0)


class TestEventBusGlobalBus(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_get_event_bus_returns_same(self):
        a = get_event_bus()
        b = get_event_bus()
        self.assertIs(a, b)

    def test_reset_event_bus_creates_new(self):
        a = get_event_bus()
        reset_event_bus()
        b = get_event_bus()
        self.assertIsNot(a, b)


class TestStateMachineAllValidTransitions(unittest.TestCase):
    def test_idle_to_starting(self):
        sm = StateMachine()
        self.assertTrue(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.STARTING)

    def test_starting_to_running(self):
        sm = StateMachine()
        sm.force_state(AppState.STARTING)
        self.assertTrue(sm.transition_to(AppState.RUNNING))
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_starting_to_stopped(self):
        sm = StateMachine()
        sm.force_state(AppState.STARTING)
        self.assertTrue(sm.transition_to(AppState.STOPPED))
        self.assertEqual(sm.state, AppState.STOPPED)

    def test_running_to_paused(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.transition_to(AppState.PAUSED))
        self.assertEqual(sm.state, AppState.PAUSED)

    def test_running_to_stopping(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.transition_to(AppState.STOPPING))
        self.assertEqual(sm.state, AppState.STOPPING)

    def test_paused_to_running(self):
        sm = StateMachine()
        sm.force_state(AppState.PAUSED)
        self.assertTrue(sm.transition_to(AppState.RUNNING))
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_paused_to_stopping(self):
        sm = StateMachine()
        sm.force_state(AppState.PAUSED)
        self.assertTrue(sm.transition_to(AppState.STOPPING))
        self.assertEqual(sm.state, AppState.STOPPING)

    def test_stopping_to_stopped(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPING)
        self.assertTrue(sm.transition_to(AppState.STOPPED))
        self.assertEqual(sm.state, AppState.STOPPED)

    def test_stopping_to_idle(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPING)
        self.assertTrue(sm.transition_to(AppState.IDLE))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_stopped_to_idle(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPED)
        self.assertTrue(sm.transition_to(AppState.IDLE))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_stopped_to_starting(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPED)
        self.assertTrue(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.STARTING)


class TestStateMachineInvalidTransitions(unittest.TestCase):
    def test_idle_to_running_invalid(self):
        sm = StateMachine()
        self.assertFalse(sm.transition_to(AppState.RUNNING))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_idle_to_stopped_invalid(self):
        sm = StateMachine()
        self.assertFalse(sm.transition_to(AppState.STOPPED))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_running_to_starting_invalid(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertFalse(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_running_to_stopped_invalid(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertFalse(sm.transition_to(AppState.STOPPED))
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_paused_to_starting_invalid(self):
        sm = StateMachine()
        sm.force_state(AppState.PAUSED)
        self.assertFalse(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.PAUSED)

    def test_stopped_to_running_invalid(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPED)
        self.assertFalse(sm.transition_to(AppState.RUNNING))
        self.assertEqual(sm.state, AppState.STOPPED)


class TestStateMachineCallbacks(unittest.TestCase):
    def test_on_transition_callback(self):
        sm = StateMachine()
        transitions = []
        sm.on_transition(lambda old, new: transitions.append((old, new)))
        sm.transition_to(AppState.STARTING)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0][0], AppState.IDLE)
        self.assertEqual(transitions[0][1], AppState.STARTING)

    def test_multiple_callbacks(self):
        sm = StateMachine()
        r1, r2 = [], []
        sm.on_transition(lambda old, new: r1.append(1))
        sm.on_transition(lambda old, new: r2.append(1))
        sm.transition_to(AppState.STARTING)
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)

    def test_callback_exception_does_not_break_others(self):
        sm = StateMachine()
        good_called = threading.Event()

        def bad_cb(old, new):
            raise RuntimeError("callback error")

        def good_cb(old, new):
            good_called.set()

        sm.on_transition(bad_cb)
        sm.on_transition(good_cb)
        sm.transition_to(AppState.STARTING)
        self.assertTrue(good_called.wait(timeout=2))

    def test_force_state_triggers_callbacks(self):
        sm = StateMachine()
        transitions = []
        sm.on_transition(lambda old, new: transitions.append((old, new)))
        sm.force_state(AppState.RUNNING)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0][1], AppState.RUNNING)


class TestStateMachineCanTransition(unittest.TestCase):
    def test_can_transition_from_idle(self):
        sm = StateMachine()
        self.assertTrue(sm.can_transition_to(AppState.STARTING))
        self.assertFalse(sm.can_transition_to(AppState.RUNNING))
        self.assertFalse(sm.can_transition_to(AppState.STOPPED))

    def test_can_transition_from_running(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.can_transition_to(AppState.PAUSED))
        self.assertTrue(sm.can_transition_to(AppState.STOPPING))
        self.assertFalse(sm.can_transition_to(AppState.STARTING))


class TestStateMachineEventBusIntegration(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_transition_emits_event(self):
        bus = EventBus()
        sm = StateMachine(bus=bus)
        received = []
        bus.subscribe(AppStateChangedEvent, lambda e: received.append(e))
        sm.transition_to(AppState.STARTING)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].old_state, "IDLE")
        self.assertEqual(received[0].new_state, "STARTING")

    def test_force_state_emits_event(self):
        bus = EventBus()
        sm = StateMachine(bus=bus)
        received = []
        bus.subscribe(AppStateChangedEvent, lambda e: received.append(e))
        sm.force_state(AppState.RUNNING)
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].new_state, "RUNNING")


if __name__ == "__main__":
    unittest.main()
