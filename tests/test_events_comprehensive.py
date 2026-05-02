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


class TestEventDataclasses(unittest.TestCase):
    def test_event_base(self):
        e = Event()
        self.assertIsInstance(e, Event)

    def test_ocr_success_event_defaults(self):
        e = OcrSuccessEvent()
        self.assertEqual(e.image_hash, "")
        self.assertEqual(e.latex, "")
        self.assertEqual(e.image_width, 0)
        self.assertEqual(e.image_height, 0)
        self.assertEqual(e.source, "")

    def test_ocr_success_event_custom(self):
        e = OcrSuccessEvent(image_hash="abc", latex="x^2", image_width=100, image_height=80, source="test")
        self.assertEqual(e.image_hash, "abc")
        self.assertEqual(e.latex, "x^2")
        self.assertEqual(e.image_width, 100)

    def test_ocr_error_event(self):
        e = OcrErrorEvent(image_hash="abc", error="timeout", source="test")
        self.assertEqual(e.error, "timeout")
        self.assertEqual(e.source, "test")

    def test_app_state_changed_event(self):
        e = AppStateChangedEvent(old_state="IDLE", new_state="RUNNING")
        self.assertEqual(e.old_state, "IDLE")
        self.assertEqual(e.new_state, "RUNNING")

    def test_config_changed_event(self):
        e = ConfigChangedEvent(payload={"interval": 2.0})
        self.assertEqual(e.payload, {"interval": 2.0})

    def test_hotkey_status_changed_event(self):
        e = HotkeyStatusChangedEvent(status={"running": True})
        self.assertEqual(e.status, {"running": True})

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
        e = OcrSuccessEvent(latex="x^2")
        with self.assertRaises(AttributeError):
            e.latex = "y^2"

    def test_event_equality(self):
        e1 = OcrSuccessEvent(latex="x^2")
        e2 = OcrSuccessEvent(latex="x^2")
        self.assertEqual(e1, e2)

    def test_event_inequality(self):
        e1 = OcrSuccessEvent(latex="x^2")
        e2 = OcrSuccessEvent(latex="y^2")
        self.assertNotEqual(e1, e2)

    def test_event_hash(self):
        e1 = OcrSuccessEvent(latex="x^2")
        e2 = OcrSuccessEvent(latex="x^2")
        self.assertEqual(hash(e1), hash(e2))


class TestEventBusSubscribe(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe(OcrSuccessEvent, lambda e: received.append(e))
        bus.emit(OcrSuccessEvent(latex="x^2"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].latex, "x^2")

    def test_multiple_subscribers(self):
        bus = EventBus()
        received1 = []
        received2 = []
        bus.subscribe(OcrSuccessEvent, lambda e: received1.append(e))
        bus.subscribe(OcrSuccessEvent, lambda e: received2.append(e))
        bus.emit(OcrSuccessEvent(latex="x^2"))
        self.assertEqual(len(received1), 1)
        self.assertEqual(len(received2), 1)

    def test_different_event_types(self):
        bus = EventBus()
        ocr_received = []
        state_received = []
        bus.subscribe(OcrSuccessEvent, lambda e: ocr_received.append(e))
        bus.subscribe(AppStateChangedEvent, lambda e: state_received.append(e))
        bus.emit(OcrSuccessEvent(latex="x^2"))
        bus.emit(AppStateChangedEvent(old_state="IDLE", new_state="RUNNING"))
        self.assertEqual(len(ocr_received), 1)
        self.assertEqual(len(state_received), 1)

    def test_emit_with_no_subscribers(self):
        bus = EventBus()
        bus.emit(OcrSuccessEvent(latex="test"))

    def test_subscriber_count(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(AppStateChangedEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 2)
        self.assertEqual(bus.subscriber_count(AppStateChangedEvent), 1)
        self.assertEqual(bus.subscriber_count(), 3)


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
        bus.emit(OcrSuccessEvent(latex="first"))
        bus.unsubscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="second"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].latex, "first")

    def test_unsubscribe_all(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(AppStateChangedEvent, lambda e: None)
        bus.unsubscribe_all()
        self.assertEqual(bus.subscriber_count(), 0)

    def test_unsubscribe_specific_event_type(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(AppStateChangedEvent, lambda e: None)
        bus.unsubscribe_all(OcrSuccessEvent)
        self.assertIsNone(bus._subscribers.get(OcrSuccessEvent))
        self.assertIn(AppStateChangedEvent, bus._subscribers)

    def test_unsubscribe_during_emit(self):
        bus = EventBus()
        called = threading.Event()

        def cb(event):
            called.set()
            bus.unsubscribe(OcrSuccessEvent, cb)

        bus.subscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertTrue(called.wait(timeout=2))


class TestEventBusSubscriberExceptions(unittest.TestCase):
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
        bus.emit(OcrSuccessEvent(latex="alive"))
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

    def test_weak_method_subscriber(self):
        bus = EventBus()
        received = []

        class Handler:
            def on_event(self, event):
                received.append(event)

        handler = Handler()
        bus.subscribe_weak(OcrSuccessEvent, handler.on_event)
        bus.emit(OcrSuccessEvent(latex="method"))
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

    def test_concurrent_emit_and_unsubscribe(self):
        bus = EventBus()
        errors = []
        cb = lambda e: None
        bus.subscribe(OcrSuccessEvent, cb)

        def emitter():
            try:
                for _ in range(50):
                    bus.emit(OcrSuccessEvent(latex="test"))
            except Exception as e:
                errors.append(e)

        def unsubscriber():
            try:
                for _ in range(50):
                    bus.unsubscribe(OcrSuccessEvent, cb)
                    bus.subscribe(OcrSuccessEvent, cb)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=emitter),
            threading.Thread(target=unsubscriber),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)


class TestEventBusClear(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_clear(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.clear()
        self.assertEqual(bus.subscriber_count(), 0)

    def test_emit_after_clear(self):
        bus = EventBus()
        received = []
        bus.subscribe(OcrSuccessEvent, lambda e: received.append(e))
        bus.clear()
        bus.emit(OcrSuccessEvent())
        self.assertEqual(len(received), 0)


class TestGlobalEventBus(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_get_event_bus_returns_same_instance(self):
        a = get_event_bus()
        b = get_event_bus()
        self.assertIs(a, b)

    def test_reset_event_bus_creates_new(self):
        a = get_event_bus()
        reset_event_bus()
        b = get_event_bus()
        self.assertIsNot(a, b)

    def test_reset_clears_subscribers(self):
        bus = get_event_bus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        reset_event_bus()
        bus2 = get_event_bus()
        self.assertEqual(bus2.subscriber_count(), 0)


if __name__ == "__main__":
    unittest.main()
