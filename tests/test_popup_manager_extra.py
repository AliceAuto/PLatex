from __future__ import annotations

import queue
import threading
import unittest

from platex_client.events import EventBus, OcrSuccessEvent, reset_event_bus
from platex_client.popup_manager import PopupManager


class TestPopupManagerShowPopup(unittest.TestCase):
    def test_show_popup_queues_item(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content", 5000)
        self.assertFalse(pm.popup_queue.empty())
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item, ("Title", "Content", 5000))

    def test_show_popup_default_timeout(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content")
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[2], 12000)


class TestPopupManagerOpenPanel(unittest.TestCase):
    def test_open_panel_queues_command(self):
        pm = PopupManager()
        pm.open_panel()
        self.assertFalse(pm.panel_queue.empty())
        item = pm.panel_queue.get_nowait()
        self.assertEqual(item, "open-panel")


class TestPopupManagerShutdown(unittest.TestCase):
    def test_request_shutdown_idempotent(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.request_shutdown()
        self.assertTrue(pm.stop_event.is_set())

    def test_confirm_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        self.assertFalse(pm._shutdown_confirmed.is_set())
        pm.confirm_shutdown()
        self.assertTrue(pm._shutdown_confirmed.is_set())

    def test_wait_for_shutdown_timeout(self):
        pm = PopupManager()
        result = pm.wait_for_shutdown(timeout=0.05)
        self.assertFalse(result)

    def test_wait_for_shutdown_confirmed(self):
        pm = PopupManager()
        pm.confirm_shutdown()
        result = pm.wait_for_shutdown(timeout=1.0)
        self.assertTrue(result)

    def test_shutdown_puts_sentinels(self):
        pm = PopupManager()
        pm.request_shutdown()
        popup_item = pm.popup_queue.get_nowait()
        panel_item = pm.panel_queue.get_nowait()
        self.assertIsNone(popup_item)
        self.assertIsNone(panel_item)


class TestPopupManagerQueueOverflow(unittest.TestCase):
    def test_queue_overflow_drops_gracefully(self):
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


class TestPopupManagerOcrEvents(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_subscribe_ocr_events(self):
        bus = EventBus()
        pm = PopupManager(bus=bus)
        pm.subscribe_ocr_events()
        self.assertGreater(bus.subscriber_count(OcrSuccessEvent), 0)

    def test_unsubscribe_ocr_events(self):
        bus = EventBus()
        pm = PopupManager(bus=bus)
        pm.subscribe_ocr_events()
        count_before = bus.subscriber_count(OcrSuccessEvent)
        self.assertGreater(count_before, 0)
        pm.unsubscribe_ocr_events()
        count_after = bus.subscriber_count(OcrSuccessEvent)
        self.assertLessEqual(count_after, count_before)

    def test_ocr_success_triggers_popup(self):
        bus = EventBus()
        pm = PopupManager(bus=bus)
        pm.subscribe_ocr_events()
        bus.emit(OcrSuccessEvent(latex=r"x^2 + y^2"))
        self.assertFalse(pm.popup_queue.empty())


class TestPopupManagerProperties(unittest.TestCase):
    def test_popup_queue_property(self):
        pm = PopupManager()
        self.assertIsInstance(pm.popup_queue, queue.Queue)

    def test_panel_queue_property(self):
        pm = PopupManager()
        self.assertIsInstance(pm.panel_queue, queue.Queue)

    def test_stop_event_property(self):
        pm = PopupManager()
        self.assertIsInstance(pm.stop_event, threading.Event)


if __name__ == "__main__":
    unittest.main()
