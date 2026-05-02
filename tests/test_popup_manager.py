from __future__ import annotations

import queue
import threading
import unittest

from platex_client.events import OcrSuccessEvent, ShutdownRequestEvent, ShowPanelEvent, reset_event_bus
from platex_client.popup_manager import PopupManager


class TestPopupManagerShowPopup(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_show_popup_not_shutdown(self):
        pm = PopupManager()
        pm.show_popup("Title", "Latex content", 5000)
        self.assertFalse(pm.popup_queue.empty())

    def test_show_popup_when_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.show_popup("Title", "Latex content")
        self.assertTrue(pm.popup_queue.empty() or pm.popup_queue.get_nowait() is None)

    def test_show_popup_default_timeout(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content")
        item = pm.popup_queue.get_nowait()
        self.assertIsNotNone(item)
        self.assertEqual(item[0], "Title")
        self.assertEqual(item[1], "Content")
        self.assertEqual(item[2], 12000)

    def test_show_popup_custom_timeout(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content", timeout_ms=5000)
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[2], 5000)


class TestPopupManagerOpenPanel(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_open_panel_not_shutdown(self):
        pm = PopupManager()
        pm.open_panel()
        self.assertFalse(pm.panel_queue.empty())

    def test_open_panel_when_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.open_panel()
        self.assertTrue(pm.panel_queue.empty() or pm.panel_queue.get_nowait() is None)

    def test_open_panel_emits_show_panel_event(self):
        pm = PopupManager()
        received = []
        pm._bus.subscribe(ShowPanelEvent, lambda e: received.append(e))
        pm.open_panel()
        self.assertEqual(len(received), 1)


class TestPopupManagerShutdown(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_request_shutdown_idempotent(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.request_shutdown()
        self.assertTrue(pm.stop_event.is_set())

    def test_shutdown_confirm(self):
        pm = PopupManager()
        pm.request_shutdown()
        self.assertFalse(pm._shutdown_confirmed.is_set())
        pm.confirm_shutdown()
        self.assertTrue(pm._shutdown_confirmed.is_set())

    def test_wait_for_shutdown_timeout(self):
        pm = PopupManager()
        result = pm.wait_for_shutdown(timeout=0.1)
        self.assertFalse(result)

    def test_wait_for_shutdown_confirmed(self):
        pm = PopupManager()
        pm.confirm_shutdown()
        result = pm.wait_for_shutdown(timeout=1.0)
        self.assertTrue(result)

    def test_request_shutdown_emits_event(self):
        pm = PopupManager()
        received = []
        pm._bus.subscribe(ShutdownRequestEvent, lambda e: received.append(e))
        pm.request_shutdown()
        self.assertEqual(len(received), 1)

    def test_request_shutdown_puts_sentinels(self):
        pm = PopupManager()
        pm.request_shutdown()
        popup_item = pm.popup_queue.get_nowait()
        panel_item = pm.panel_queue.get_nowait()
        self.assertIsNone(popup_item)
        self.assertIsNone(panel_item)


class TestPopupManagerQueueOverflow(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

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
        pm = PopupManager()
        pm.subscribe_ocr_events()
        self.assertGreater(pm._bus.subscriber_count(OcrSuccessEvent), 0)
        pm.unsubscribe_ocr_events()

    def test_unsubscribe_ocr_events(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        pm.unsubscribe_ocr_events()
        self.assertEqual(pm._bus.subscriber_count(OcrSuccessEvent), 0)

    def test_ocr_success_shows_popup(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        pm._bus.emit(OcrSuccessEvent(latex="x^2"))
        self.assertFalse(pm.popup_queue.empty())
        pm.unsubscribe_ocr_events()

    def test_ocr_success_when_shutdown(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        pm.request_shutdown()
        pm._bus.emit(OcrSuccessEvent(latex="x^2"))
        self.assertTrue(pm.popup_queue.empty() or pm.popup_queue.get_nowait() is None)
        pm.unsubscribe_ocr_events()


class TestPopupManagerProperties(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
