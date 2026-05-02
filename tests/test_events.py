from __future__ import annotations

import gc
import threading
import unittest
import weakref

from platex_client.events import (
    AppStateChangedEvent,
    ClipboardPublishingEvent,
    ConfigChangedEvent,
    Event,
    EventBus,
    HotkeyStatusChangedEvent,
    OcrErrorEvent,
    OcrSuccessEvent,
    ShowPanelEvent,
    ShutdownRequestEvent,
    get_event_bus,
    reset_event_bus,
)


class TestEventTypes(unittest.TestCase):
    def test_base_event(self):
        e = Event()
        self.assertIsInstance(e, Event)

    def test_ocr_success_event(self):
        e = OcrSuccessEvent(latex="x^2", image_hash="abc", source="test")
        self.assertEqual(e.latex, "x^2")
        self.assertEqual(e.image_hash, "abc")
        self.assertEqual(e.source, "test")

    def test_ocr_error_event(self):
        e = OcrErrorEvent(error="failed", image_hash="abc", source="test")
        self.assertEqual(e.error, "failed")

    def test_app_state_changed_event(self):
        e = AppStateChangedEvent(old_state="IDLE", new_state="RUNNING")
        self.assertEqual(e.old_state, "IDLE")
        self.assertEqual(e.new_state, "RUNNING")

    def test_config_changed_event(self):
        e = ConfigChangedEvent(payload={"interval": 2.0})
        self.assertEqual(e.payload["interval"], 2.0)

    def test_hotkey_status_changed_event(self):
        e = HotkeyStatusChangedEvent(status={"running": True})
        self.assertTrue(e.status["running"])

    def test_clipboard_publishing_event(self):
        e = ClipboardPublishingEvent(is_publishing=True)
        self.assertTrue(e.is_publishing)

    def test_show_panel_event(self):
        e = ShowPanelEvent()
        self.assertIsInstance(e, Event)

    def test_shutdown_request_event(self):
        e = ShutdownRequestEvent()
        self.assertIsInstance(e, Event)

    def test_events_are_frozen(self):
        e = OcrSuccessEvent(latex="x")
        with self.assertRaises(AttributeError):
            e.latex = "y"

    def test_event_equality(self):
        e1 = OcrSuccessEvent(latex="x", image_hash="h")
        e2 = OcrSuccessEvent(latex="x", image_hash="h")
        self.assertEqual(e1, e2)

    def test_event_inequality(self):
        e1 = OcrSuccessEvent(latex="x")
        e2 = OcrSuccessEvent(latex="y")
        self.assertNotEqual(e1, e2)

    def test_default_values(self):
        e = OcrSuccessEvent()
        self.assertEqual(e.latex, "")
        self.assertEqual(e.image_hash, "")
        self.assertEqual(e.image_width, 0)
        self.assertEqual(e.image_height, 0)
        self.assertEqual(e.source, "")


class TestEventBusSubscribe(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe(OcrSuccessEvent, lambda e: received.append(e))
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].latex, "test")

    def test_multiple_subscribers(self):
        bus = EventBus()
        r1, r2 = [], []
        bus.subscribe(OcrSuccessEvent, lambda e: r1.append(e))
        bus.subscribe(OcrSuccessEvent, lambda e: r2.append(e))
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(r1), 1)
        self.assertEqual(len(r2), 1)

    def test_subscriber_only_receives_matching_type(self):
        bus = EventBus()
        received = []
        bus.subscribe(OcrSuccessEvent, lambda e: received.append(e))
        bus.emit(OcrErrorEvent(error="fail"))
        self.assertEqual(len(received), 0)

    def test_emit_with_no_subscribers(self):
        bus = EventBus()
        bus.emit(OcrSuccessEvent(latex="test"))

    def test_subscriber_count(self):
        bus = EventBus()
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 0)
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 1)
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 2)

    def test_total_subscriber_count(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrErrorEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(), 2)


class TestEventBusUnsubscribe(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        cb = lambda e: received.append(e)
        bus.subscribe(OcrSuccessEvent, cb)
        bus.unsubscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(received), 0)

    def test_unsubscribe_specific_callback(self):
        bus = EventBus()
        r1, r2 = [], []
        cb1 = lambda e: r1.append(e)
        cb2 = lambda e: r2.append(e)
        bus.subscribe(OcrSuccessEvent, cb1)
        bus.subscribe(OcrSuccessEvent, cb2)
        bus.unsubscribe(OcrSuccessEvent, cb1)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(r1), 0)
        self.assertEqual(len(r2), 1)

    def test_unsubscribe_all(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrErrorEvent, lambda e: None)
        bus.unsubscribe_all()
        self.assertEqual(bus.subscriber_count(), 0)

    def test_unsubscribe_all_specific_type(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrErrorEvent, lambda e: None)
        bus.unsubscribe_all(OcrSuccessEvent)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 0)
        self.assertEqual(bus.subscriber_count(OcrErrorEvent), 1)


class TestEventBusWeakSubscribe(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_weak_subscriber_receives_events(self):
        bus = EventBus()
        received = []

        class Handler:
            def __call__(self, event):
                received.append(event)

        handler = Handler()
        bus.subscribe_weak(OcrSuccessEvent, handler)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(received), 1)

    def test_weak_subscriber_gc_cleanup(self):
        bus = EventBus()
        received = []

        class Handler:
            def __call__(self, event):
                received.append(event)

        handler = Handler()
        bus.subscribe_weak(OcrSuccessEvent, handler)
        bus.emit(OcrSuccessEvent(latex="alive"))
        self.assertEqual(len(received), 1)

        ref = weakref.ref(handler)
        del handler
        gc.collect()

        bus.emit(OcrSuccessEvent(latex="after_gc"))
        self.assertIsNone(ref())
        self.assertEqual(len(received), 1)


class TestEventBusErrorHandling(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_subscriber_exception_does_not_break_others(self):
        bus = EventBus()
        bad_called = threading.Event()
        good_called = threading.Event()

        def bad_cb(event):
            bad_called.set()
            raise RuntimeError("subscriber error")

        def good_cb(event):
            good_called.set()

        bus.subscribe(OcrSuccessEvent, bad_cb)
        bus.subscribe(OcrSuccessEvent, good_cb)
        bus.emit(OcrSuccessEvent(latex="test"))

        self.assertTrue(bad_called.wait(timeout=2))
        self.assertTrue(good_called.wait(timeout=2))

    def test_unsubscribe_during_emit(self):
        bus = EventBus()
        called = threading.Event()

        def cb(event):
            called.set()
            bus.unsubscribe(OcrSuccessEvent, cb)

        bus.subscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertTrue(called.wait(timeout=2))


class TestEventBusClear(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_clear_removes_all_subscribers(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrErrorEvent, lambda e: None)
        bus.clear()
        self.assertEqual(bus.subscriber_count(), 0)

    def test_clear_then_subscribe(self):
        bus = EventBus()
        received = []
        bus.subscribe(OcrSuccessEvent, lambda e: received.append(e))
        bus.clear()
        bus.subscribe(OcrSuccessEvent, lambda e: received.append(e))
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertEqual(len(received), 1)


class TestEventBusConcurrency(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_concurrent_subscribe_and_emit(self):
        bus = EventBus()
        errors = []

        def subscriber():
            try:
                for _ in range(50):
                    bus.subscribe(OcrSuccessEvent, lambda e: None)
            except Exception as e:
                errors.append(e)

        def emitter():
            try:
                for _ in range(50):
                    bus.emit(OcrSuccessEvent(latex="test"))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=subscriber),
            threading.Thread(target=emitter),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0)


class TestGlobalEventBus(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_get_event_bus_returns_same_instance(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        self.assertIs(bus1, bus2)

    def test_reset_creates_new_instance(self):
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        self.assertIsNot(bus1, bus2)

    def test_reset_clears_subscribers(self):
        bus = get_event_bus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        reset_event_bus()
        bus2 = get_event_bus()
        self.assertEqual(bus2.subscriber_count(), 0)


if __name__ == "__main__":
    unittest.main()
