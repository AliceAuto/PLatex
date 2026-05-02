from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from platex_client.history import HistoryStore
from platex_client.models import ClipboardEvent, ClipboardImage, OcrProcessor
from platex_client.watcher import ClipboardWatcher


class _DummyProcessor(OcrProcessor):
    def process_image(self, image_bytes, context=None):
        return "test"


class _SlowProcessor(OcrProcessor):
    def process_image(self, image_bytes, context=None):
        time.sleep(0.3)
        return "slow"


class _FailingProcessor(OcrProcessor):
    def process_image(self, image_bytes, context=None):
        raise RuntimeError("OCR engine failure")


class _HangingProcessor(OcrProcessor):
    def process_image(self, image_bytes, context=None):
        time.sleep(10)
        return "never"


def _make_watcher(processor=None, history=None, ocr_timeout=120.0):
    if processor is None:
        processor = _DummyProcessor()
    if history is None:
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "test.sqlite3"
        history = HistoryStore(db_path)
    return ClipboardWatcher(
        processor=processor,
        history=history,
        source_name="test",
        ocr_timeout=ocr_timeout,
    )


class TestClipboardWatcherPollOnceAsync(unittest.TestCase):
    def test_async_poll_no_image(self):
        watcher = _make_watcher()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=None):
            result = watcher.poll_once_async(lambda e: None)
        self.assertFalse(result)
        watcher.close()

    def test_async_poll_while_paused(self):
        watcher = _make_watcher()
        watcher.set_publishing(True)
        result = watcher.poll_once_async(lambda e: None)
        self.assertFalse(result)
        watcher.set_publishing(False)
        watcher.close()

    def test_async_poll_while_ocr_running(self):
        watcher = _make_watcher()
        watcher._ocr_running.set()
        result = watcher.poll_once_async(lambda e: None)
        self.assertFalse(result)
        watcher._ocr_running.clear()
        watcher.close()

    def test_async_poll_success(self):
        watcher = _make_watcher()
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        result_event = threading.Event()
        result_holder = [None]

        def callback(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            started = watcher.poll_once_async(callback)
        self.assertTrue(started)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0].status, "ok")
        self.assertEqual(result_holder[0].latex, "test")
        watcher.close()

    def test_async_poll_failure(self):
        watcher = _make_watcher(processor=_FailingProcessor())
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        result_event = threading.Event()
        result_holder = [None]

        def callback(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            started = watcher.poll_once_async(callback)
        self.assertTrue(started)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0].status, "error")
        watcher.close()

    def test_async_poll_timeout(self):
        watcher = _make_watcher(processor=_HangingProcessor(), ocr_timeout=0.5)
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        result_event = threading.Event()
        result_holder = [None]

        def callback(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            started = watcher.poll_once_async(callback)
        self.assertTrue(started)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0].status, "error")
        self.assertIn("timed out", result_holder[0].error)
        watcher.close()

    def test_async_poll_duplicate_image_skipped(self):
        watcher = _make_watcher()
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            watcher.poll_once()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once_async(lambda e: None)
        self.assertFalse(result)
        watcher.close()

    def test_async_poll_callback_exception_handled(self):
        watcher = _make_watcher()
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)

        def bad_callback(event):
            raise RuntimeError("callback error")

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            started = watcher.poll_once_async(bad_callback)
        self.assertTrue(started)
        time.sleep(0.5)
        watcher.close()


class TestClipboardWatcherPollOnceEdgeCases(unittest.TestCase):
    def test_poll_force_ignores_duplicate(self):
        watcher = _make_watcher()
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result1 = watcher.poll_once()
        self.assertIsNotNone(result1)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result2 = watcher.poll_once(force=True)
        self.assertIsNotNone(result2)
        watcher.close()

    def test_close_waits_for_ocr(self):
        watcher = _make_watcher(processor=_SlowProcessor(), ocr_timeout=5.0)
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            poll_thread = threading.Thread(target=watcher.poll_once)
            poll_thread.start()
            time.sleep(0.1)
        watcher.close()
        poll_thread.join(timeout=5)

    def test_history_write_failure_does_not_crash(self):
        class FailingHistory:
            def add(self, event):
                raise RuntimeError("db locked")

            def close(self):
                pass

        watcher = ClipboardWatcher(
            processor=_DummyProcessor(),
            history=FailingHistory(),
            source_name="test",
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        watcher.close()


class TestClipboardWatcherSetPublishing(unittest.TestCase):
    def test_set_publishing_true(self):
        watcher = _make_watcher()
        watcher.set_publishing(True)
        self.assertTrue(watcher._paused.is_set())
        watcher.close()

    def test_set_publishing_false(self):
        watcher = _make_watcher()
        watcher.set_publishing(True)
        watcher.set_publishing(False)
        self.assertFalse(watcher._paused.is_set())
        watcher.close()


class TestClipboardWatcherCleanupOrphanThreads(unittest.TestCase):
    def test_cleanup_dead_threads(self):
        watcher = _make_watcher()
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()
        watcher._orphan_threads.append(dead_thread)
        watcher._cleanup_orphan_threads()
        self.assertEqual(len(watcher._orphan_threads), 0)
        watcher.close()


if __name__ == "__main__":
    unittest.main()
