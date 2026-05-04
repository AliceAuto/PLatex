from __future__ import annotations

import queue
import threading
import time
import unittest

from platex_client.events import (
    EventBus,
    OcrSuccessEvent,
    ShowPanelEvent,
    ShutdownRequestEvent,
    reset_event_bus,
)
from platex_client.popup_manager import PopupManager, _MAX_QUEUE_SIZE


class TestShowPopup(unittest.TestCase):
    """Tests for show_popup method."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_show_popup_enqueues_tuple(self):
        pm = PopupManager()
        pm.show_popup("Title", "Latex content", 5000)
        self.assertFalse(pm.popup_queue.empty())
        item = pm.popup_queue.get_nowait()
        self.assertIsNotNone(item)
        self.assertEqual(item, ("Title", "Latex content", 5000))

    def test_show_popup_default_timeout(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content")
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[2], 12000)

    def test_show_popup_custom_timeout(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content", timeout_ms=3000)
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[2], 3000)

    def test_show_popup_preserves_title_and_latex(self):
        pm = PopupManager()
        pm.show_popup("My Title", r"\alpha + \beta")
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[0], "My Title")
        self.assertEqual(item[1], r"\alpha + \beta")

    def test_show_popup_unicode_content(self):
        pm = PopupManager()
        pm.show_popup("Title", "alpha + beta = gamma")
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[1], "alpha + beta = gamma")

    def test_show_popup_empty_strings(self):
        pm = PopupManager()
        pm.show_popup("", "", 1000)
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item, ("", "", 1000))


class TestShowPopupWhenShutdown(unittest.TestCase):
    """Tests for show_popup when shutdown is in progress."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_show_popup_when_shutdown_does_not_enqueue(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.show_popup("Title", "Content")
        data_count = 0
        while not pm.popup_queue.empty():
            item = pm.popup_queue.get_nowait()
            if item is not None:
                data_count += 1
        self.assertEqual(data_count, 0)

    def test_show_popup_after_shutdown_only_sentinels(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.show_popup("Title1", "Content1")
        pm.show_popup("Title2", "Content2")
        sentinel_count = 0
        data_count = 0
        while not pm.popup_queue.empty():
            item = pm.popup_queue.get_nowait()
            if item is None:
                sentinel_count += 1
            else:
                data_count += 1
        self.assertEqual(data_count, 0)
        self.assertGreaterEqual(sentinel_count, 1)


class TestOpenPanel(unittest.TestCase):
    """Tests for open_panel method."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_open_panel_enqueues_string(self):
        pm = PopupManager()
        pm.open_panel()
        self.assertFalse(pm.panel_queue.empty())
        item = pm.panel_queue.get_nowait()
        self.assertEqual(item, "open-panel")

    def test_open_panel_emits_show_panel_event(self):
        pm = PopupManager()
        received = []
        pm._bus.subscribe(ShowPanelEvent, lambda e: received.append(e))
        pm.open_panel()
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], ShowPanelEvent)

    def test_open_panel_multiple_times(self):
        pm = PopupManager()
        pm.open_panel()
        pm.open_panel()
        pm.open_panel()
        count = 0
        while not pm.panel_queue.empty():
            pm.panel_queue.get_nowait()
            count += 1
        self.assertEqual(count, 3)


class TestOpenPanelWhenShutdown(unittest.TestCase):
    """Tests for open_panel when shutdown is in progress."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_open_panel_when_shutdown_does_not_enqueue(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.open_panel()
        data_count = 0
        while not pm.panel_queue.empty():
            item = pm.panel_queue.get_nowait()
            if item is not None:
                data_count += 1
        self.assertEqual(data_count, 0)

    def test_open_panel_after_shutdown_emits_no_event(self):
        pm = PopupManager()
        received = []
        pm._bus.subscribe(ShowPanelEvent, lambda e: received.append(e))
        pm.request_shutdown()
        pm.open_panel()
        # The shutdown request itself does not emit ShowPanelEvent
        # open_panel after shutdown should not emit either
        show_panel_count = sum(1 for e in received if isinstance(e, ShowPanelEvent))
        self.assertEqual(show_panel_count, 0)


class TestRequestShutdownIdempotent(unittest.TestCase):
    """Tests for request_shutdown idempotency."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_request_shutdown_idempotent(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.request_shutdown()
        pm.request_shutdown()
        self.assertTrue(pm.stop_event.is_set())

    def test_multiple_shutdowns_single_sentinel(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.request_shutdown()
        sentinel_count = 0
        while not pm.popup_queue.empty():
            item = pm.popup_queue.get_nowait()
            if item is None:
                sentinel_count += 1
        self.assertEqual(sentinel_count, 1)

    def test_shutdown_sets_stop_event(self):
        pm = PopupManager()
        self.assertFalse(pm.stop_event.is_set())
        pm.request_shutdown()
        self.assertTrue(pm.stop_event.is_set())

    def test_shutdown_puts_sentinels_in_both_queues(self):
        pm = PopupManager()
        pm.request_shutdown()
        popup_item = pm.popup_queue.get_nowait()
        panel_item = pm.panel_queue.get_nowait()
        self.assertIsNone(popup_item)
        self.assertIsNone(panel_item)

    def test_shutdown_emits_shutdown_request_event(self):
        pm = PopupManager()
        received = []
        pm._bus.subscribe(ShutdownRequestEvent, lambda e: received.append(e))
        pm.request_shutdown()
        self.assertEqual(len(received), 1)
        self.assertIsInstance(received[0], ShutdownRequestEvent)

    def test_idempotent_shutdown_emits_single_event(self):
        pm = PopupManager()
        received = []
        pm._bus.subscribe(ShutdownRequestEvent, lambda e: received.append(e))
        pm.request_shutdown()
        pm.request_shutdown()
        pm.request_shutdown()
        self.assertEqual(len(received), 1)


class TestWaitForShutdownTimeout(unittest.TestCase):
    """Tests for wait_for_shutdown timeout behavior."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_wait_for_shutdown_timeout_returns_false(self):
        pm = PopupManager()
        result = pm.wait_for_shutdown(timeout=0.05)
        self.assertFalse(result)

    def test_wait_for_shutdown_confirmed_returns_true(self):
        pm = PopupManager()
        pm.confirm_shutdown()
        result = pm.wait_for_shutdown(timeout=1.0)
        self.assertTrue(result)

    def test_wait_for_shutdown_after_request_and_confirm(self):
        pm = PopupManager()
        pm.request_shutdown()
        self.assertFalse(pm._shutdown_confirmed.is_set())
        pm.confirm_shutdown()
        result = pm.wait_for_shutdown(timeout=1.0)
        self.assertTrue(result)

    def test_wait_for_shutdown_zero_timeout(self):
        pm = PopupManager()
        result = pm.wait_for_shutdown(timeout=0)
        self.assertFalse(result)

    def test_wait_for_shutdown_negative_timeout(self):
        pm = PopupManager()
        result = pm.wait_for_shutdown(timeout=-1)
        self.assertFalse(result)


class TestConfirmShutdown(unittest.TestCase):
    """Tests for confirm_shutdown method."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_confirm_shutdown_sets_event(self):
        pm = PopupManager()
        self.assertFalse(pm._shutdown_confirmed.is_set())
        pm.confirm_shutdown()
        self.assertTrue(pm._shutdown_confirmed.is_set())

    def test_confirm_shutdown_idempotent(self):
        pm = PopupManager()
        pm.confirm_shutdown()
        pm.confirm_shutdown()
        self.assertTrue(pm._shutdown_confirmed.is_set())

    def test_confirm_without_request(self):
        pm = PopupManager()
        pm.confirm_shutdown()
        self.assertTrue(pm._shutdown_confirmed.is_set())
        self.assertFalse(pm.stop_event.is_set())


class TestQueueOverflow(unittest.TestCase):
    """Tests for queue overflow handling."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_max_queue_size_constant(self):
        self.assertEqual(_MAX_QUEUE_SIZE, 50)

    def test_popup_queue_overflow_drops_gracefully(self):
        pm = PopupManager()
        pm._popup_queue = queue.Queue(maxsize=3)
        for i in range(10):
            pm.show_popup("Title", f"Content {i}")
        count = 0
        while not pm.popup_queue.empty():
            try:
                pm.popup_queue.get_nowait()
                count += 1
            except queue.Empty:
                break
        self.assertLessEqual(count, 3)

    def test_panel_queue_overflow_logs_warning(self):
        pm = PopupManager()
        pm._panel_queue = queue.Queue(maxsize=2)
        for i in range(10):
            pm.open_panel()
        count = 0
        while not pm.panel_queue.empty():
            try:
                pm.panel_queue.get_nowait()
                count += 1
            except queue.Empty:
                break
        self.assertLessEqual(count, 2)

    def test_popup_queue_default_maxsize(self):
        pm = PopupManager()
        self.assertEqual(pm.popup_queue.maxsize, _MAX_QUEUE_SIZE)

    def test_panel_queue_default_maxsize(self):
        pm = PopupManager()
        self.assertEqual(pm.panel_queue.maxsize, _MAX_QUEUE_SIZE)


class TestSubscribeUnsubscribeOcrEvents(unittest.TestCase):
    """Tests for subscribe_ocr_events and unsubscribe_ocr_events."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_subscribe_ocr_events(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        self.assertGreater(pm._bus.subscriber_count(OcrSuccessEvent), 0)

    def test_unsubscribe_ocr_events(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        count_before = pm._bus.subscriber_count(OcrSuccessEvent)
        pm.unsubscribe_ocr_events()
        count_after = pm._bus.subscriber_count(OcrSuccessEvent)
        self.assertLessEqual(count_after, count_before)

    def test_subscribe_unsubscribe_cycle(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        pm.unsubscribe_ocr_events()
        pm.subscribe_ocr_events()
        self.assertGreater(pm._bus.subscriber_count(OcrSuccessEvent), 0)

    def test_unsubscribe_without_subscribe(self):
        pm = PopupManager()
        pm.unsubscribe_ocr_events()
        # Should not raise


class TestOnOcrSuccess(unittest.TestCase):
    """Tests for _on_ocr_success callback."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_on_ocr_success_shows_popup(self):
        pm = PopupManager()
        pm._on_ocr_success(OcrSuccessEvent(latex="x^2"))
        self.assertFalse(pm.popup_queue.empty())
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[1], "x^2")

    def test_on_ocr_success_title(self):
        pm = PopupManager()
        pm._on_ocr_success(OcrSuccessEvent(latex="y^2"))
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[0], "PLatex OCR Success")

    def test_on_ocr_success_default_timeout(self):
        pm = PopupManager()
        pm._on_ocr_success(OcrSuccessEvent(latex="z^2"))
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[2], 12000)

    def test_on_ocr_success_when_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm._on_ocr_success(OcrSuccessEvent(latex="x^2"))
        data_count = 0
        while not pm.popup_queue.empty():
            item = pm.popup_queue.get_nowait()
            if item is not None:
                data_count += 1
        self.assertEqual(data_count, 0)

    def test_on_ocr_success_with_empty_latex(self):
        pm = PopupManager()
        pm._on_ocr_success(OcrSuccessEvent(latex=""))
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[1], "")


class TestEventBusIntegration(unittest.TestCase):
    """Tests for event bus integration with PopupManager."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_custom_event_bus(self):
        custom_bus = EventBus()
        pm = PopupManager(bus=custom_bus)
        self.assertIs(pm._bus, custom_bus)

    def test_default_event_bus(self):
        pm = PopupManager()
        self.assertIsNotNone(pm._bus)

    def test_ocr_event_triggers_popup_via_bus(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        pm._bus.emit(OcrSuccessEvent(latex="x^2 + y^2"))
        self.assertFalse(pm.popup_queue.empty())
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[1], "x^2 + y^2")

    def test_shutdown_event_via_bus(self):
        pm = PopupManager()
        received = []
        pm._bus.subscribe(ShutdownRequestEvent, lambda e: received.append(e))
        pm.request_shutdown()
        self.assertEqual(len(received), 1)

    def test_show_panel_event_via_bus(self):
        pm = PopupManager()
        received = []
        pm._bus.subscribe(ShowPanelEvent, lambda e: received.append(e))
        pm.open_panel()
        self.assertEqual(len(received), 1)

    def test_multiple_subscribers_on_same_bus(self):
        pm1 = PopupManager()
        pm2 = PopupManager()
        pm1.subscribe_ocr_events()
        pm2.subscribe_ocr_events()
        pm1._bus.emit(OcrSuccessEvent(latex="test"))
        # Both should receive the event
        self.assertFalse(pm1.popup_queue.empty())
        self.assertFalse(pm2.popup_queue.empty())


class TestPopupManagerProperties(unittest.TestCase):
    """Tests for PopupManager property accessors."""

    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_popup_queue_property(self):
        pm = PopupManager()
        self.assertIsInstance(pm.popup_queue, queue.Queue)

    def test_panel_queue_property(self):
        pm = PopupManager()
        self.assertIsInstance(pm.panel_queue, queue.Queue)

    def test_stop_event_property(self):
        pm = PopupManager()
        self.assertIsInstance(pm.stop_event, threading.Event)
        self.assertFalse(pm.stop_event.is_set())

    def test_stop_event_initially_unset(self):
        pm = PopupManager()
        self.assertFalse(pm.stop_event.is_set())

    def test_shutdown_confirmed_initially_unset(self):
        pm = PopupManager()
        self.assertFalse(pm._shutdown_confirmed.is_set())


if __name__ == "__main__":
    unittest.main()
