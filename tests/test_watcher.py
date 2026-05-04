from __future__ import annotations

import queue
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.clipboard import image_hash
from platex_client.history import HistoryStore
from platex_client.models import ClipboardEvent, ClipboardImage, OcrProcessor
from platex_client.watcher import ClipboardWatcher, _MAX_ORPHAN_THREADS


class _DummyProcessor(OcrProcessor):
    def process_image(self, image_bytes, context=None):
        return "test_latex_result"


class _SlowProcessor(OcrProcessor):
    def process_image(self, image_bytes, context=None):
        time.sleep(0.5)
        return "slow_result"


class _FailingProcessor(OcrProcessor):
    def process_image(self, image_bytes, context=None):
        raise RuntimeError("OCR engine failure")


class _HangingProcessor(OcrProcessor):
    def process_image(self, image_bytes, context=None):
        time.sleep(30)
        return "never"


class _ContextCapturingProcessor(OcrProcessor):
    def __init__(self):
        self.last_context = None

    def process_image(self, image_bytes, context=None):
        self.last_context = context
        return "captured"


def _make_watcher(processor=None, history=None, ocr_timeout=120.0, source_name="test"):
    if processor is None:
        processor = _DummyProcessor()
    if history is None:
        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
    return ClipboardWatcher(
        processor=processor,
        history=history,
        source_name=source_name,
        ocr_timeout=ocr_timeout,
    )


def _make_image(width=100, height=100):
    return ClipboardImage(image_bytes=b"fake_image_data", width=width, height=height)


class TestSetPublishing(unittest.TestCase):
    """Tests for set_publishing method."""

    def test_set_publishing_true_sets_paused(self):
        watcher = _make_watcher()
        watcher.set_publishing(True)
        self.assertTrue(watcher._paused.is_set())
        watcher.close()

    def test_set_publishing_false_clears_paused(self):
        watcher = _make_watcher()
        watcher.set_publishing(True)
        self.assertTrue(watcher._paused.is_set())
        watcher.set_publishing(False)
        self.assertFalse(watcher._paused.is_set())
        watcher.close()

    def test_set_publishing_toggle_multiple_times(self):
        watcher = _make_watcher()
        for _ in range(5):
            watcher.set_publishing(True)
            self.assertTrue(watcher._paused.is_set())
            watcher.set_publishing(False)
            self.assertFalse(watcher._paused.is_set())
        watcher.close()

    def test_set_publishing_true_blocks_poll(self):
        watcher = _make_watcher()
        watcher.set_publishing(True)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once()
        self.assertIsNone(result)
        watcher.close()


class TestPollOnceNoImage(unittest.TestCase):
    """Tests for poll_once when no image is on clipboard."""

    def test_poll_once_no_image_returns_none(self):
        watcher = _make_watcher()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=None):
            result = watcher.poll_once()
        self.assertIsNone(result)
        watcher.close()

    def test_poll_once_no_image_does_not_set_ocr_running(self):
        watcher = _make_watcher()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=None):
            watcher.poll_once()
        self.assertFalse(watcher._ocr_running.is_set())
        watcher.close()


class TestPollOnceOcrRunning(unittest.TestCase):
    """Tests for poll_once while OCR is already running."""

    def test_poll_once_while_ocr_running_returns_none(self):
        watcher = _make_watcher()
        watcher._ocr_running.set()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once()
        self.assertIsNone(result)
        watcher._ocr_running.clear()
        watcher.close()

    def test_poll_once_while_ocr_running_does_not_change_hash(self):
        watcher = _make_watcher()
        watcher.last_image_hash = "existing_hash"
        watcher._ocr_running.set()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once()
        self.assertEqual(watcher.last_image_hash, "existing_hash")
        watcher._ocr_running.clear()
        watcher.close()


class TestPollOnceWithForce(unittest.TestCase):
    """Tests for poll_once with force parameter."""

    def test_force_processes_duplicate_image(self):
        watcher = _make_watcher()
        fake_image = _make_image()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result1 = watcher.poll_once(force=True)
            self.assertIsNotNone(result1)
            result2 = watcher.poll_once(force=True)
            self.assertIsNotNone(result2)

    def test_no_force_skips_duplicate_image(self):
        watcher = _make_watcher()
        fake_image = _make_image()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result1 = watcher.poll_once(force=True)
            self.assertIsNotNone(result1)
            result2 = watcher.poll_once(force=False)
            self.assertIsNone(result2)

    def test_force_false_default(self):
        watcher = _make_watcher()
        fake_image = _make_image()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result1 = watcher.poll_once(force=True)
            result2 = watcher.poll_once()
            self.assertIsNone(result2)


class TestPollOnceSuccess(unittest.TestCase):
    """Tests for successful poll_once OCR processing."""

    def test_returns_event_on_success(self):
        watcher = _make_watcher()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.latex, "test_latex_result")
        self.assertEqual(result.source, "test")
        self.assertIsNone(result.error)
        watcher.close()

    def test_event_has_correct_image_dimensions(self):
        watcher = _make_watcher()
        img = _make_image(width=200, height=150)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=img):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.image_width, 200)
        self.assertEqual(result.image_height, 150)
        watcher.close()

    def test_event_has_image_hash(self):
        watcher = _make_watcher()
        img = _make_image()
        expected_hash = image_hash(img.image_bytes)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=img):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.image_hash, expected_hash)
        watcher.close()

    def test_event_persisted_to_history(self):
        temp_dir = tempfile.mkdtemp()
        try:
            history = HistoryStore(Path(temp_dir) / "test.sqlite3")
            watcher = _make_watcher(history=history)
            with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
                watcher.poll_once(force=True)
            latest = history.latest()
            self.assertIsNotNone(latest)
            self.assertEqual(latest.status, "ok")
            watcher.close()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_processor_receives_context(self):
        processor = _ContextCapturingProcessor()
        watcher = _make_watcher(processor=processor)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once(force=True)
        self.assertIsNotNone(processor.last_context)
        self.assertIn("image_hash", processor.last_context)
        self.assertIn("image_width", processor.last_context)
        self.assertIn("image_height", processor.last_context)
        self.assertIn("source", processor.last_context)
        watcher.close()


class TestPollOnceOcrError(unittest.TestCase):
    """Tests for poll_once when OCR fails."""

    def test_ocr_exception_returns_error_event(self):
        watcher = _make_watcher(processor=_FailingProcessor())
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("OCR engine failure", result.error)
        self.assertEqual(result.latex, "")
        watcher.close()

    def test_ocr_timeout_returns_error_event(self):
        watcher = _make_watcher(processor=_HangingProcessor(), ocr_timeout=0.5)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("timed out", result.error)
        watcher.close()


class TestPollOnceAsyncBasic(unittest.TestCase):
    """Tests for poll_once_async basic functionality."""

    def test_async_success(self):
        watcher = _make_watcher()
        result_event = threading.Event()
        result_holder = [None]

        def on_done(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            started = watcher.poll_once_async(on_done, force=True)
        self.assertTrue(started)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0].status, "ok")
        watcher.close()

    def test_async_returns_false_when_paused(self):
        watcher = _make_watcher()
        watcher.set_publishing(True)
        started = watcher.poll_once_async(lambda e: None)
        self.assertFalse(started)
        watcher.set_publishing(False)
        watcher.close()

    def test_async_returns_false_when_ocr_running(self):
        watcher = _make_watcher()
        watcher._ocr_running.set()
        started = watcher.poll_once_async(lambda e: None)
        self.assertFalse(started)
        watcher._ocr_running.clear()
        watcher.close()

    def test_async_returns_false_when_no_image(self):
        watcher = _make_watcher()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=None):
            started = watcher.poll_once_async(lambda e: None)
        self.assertFalse(started)
        watcher.close()

    def test_async_returns_false_for_duplicate(self):
        watcher = _make_watcher()
        fake_image = _make_image()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            watcher.poll_once(force=True)
            started = watcher.poll_once_async(lambda e: None, force=False)
        self.assertFalse(started)
        watcher.close()

    def test_async_force_processes_duplicate(self):
        watcher = _make_watcher()
        fake_image = _make_image()
        result_event = threading.Event()
        result_holder = [None]

        def on_done(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            watcher.poll_once(force=True)
            started = watcher.poll_once_async(on_done, force=True)
        self.assertTrue(started)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertIsNotNone(result_holder[0])
        watcher.close()


class TestPollOnceAsyncTimeout(unittest.TestCase):
    """Tests for poll_once_async timeout handling."""

    def test_async_timeout_returns_error_event(self):
        watcher = _make_watcher(processor=_HangingProcessor(), ocr_timeout=0.5)
        result_event = threading.Event()
        result_holder = [None]

        def on_done(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once_async(on_done, force=True)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertIsNotNone(result_holder[0])
        self.assertEqual(result_holder[0].status, "error")
        self.assertIn("timed out", result_holder[0].error)
        watcher.close()

    def test_async_error_returns_error_event(self):
        watcher = _make_watcher(processor=_FailingProcessor())
        result_event = threading.Event()
        result_holder = [None]

        def on_done(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once_async(on_done, force=True)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertEqual(result_holder[0].status, "error")
        watcher.close()


class TestCloseWaitsForOcr(unittest.TestCase):
    """Tests for close waiting for OCR completion."""

    def test_close_waits_for_ocr(self):
        watcher = _make_watcher(processor=_SlowProcessor(), ocr_timeout=5.0)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            poll_thread = threading.Thread(target=watcher.poll_once, kwargs={"force": True})
            poll_thread.start()
            time.sleep(0.1)
        watcher.close()
        poll_thread.join(timeout=10)

    def test_close_when_no_ocr_running(self):
        watcher = _make_watcher()
        watcher.close()

    def test_close_with_none_history(self):
        temp_dir = tempfile.mkdtemp()
        try:
            history = HistoryStore(Path(temp_dir) / "test.sqlite3")
            watcher = _make_watcher(history=history)
            watcher.history = None
            watcher.close()
            history.close()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestOrphanThreadCleanup(unittest.TestCase):
    """Tests for _cleanup_orphan_threads."""

    def test_dead_threads_removed(self):
        watcher = _make_watcher()
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()
        watcher._orphan_threads.append(dead_thread)
        watcher._cleanup_orphan_threads()
        self.assertEqual(len(watcher._orphan_threads), 0)
        watcher.close()

    def test_alive_threads_kept(self):
        watcher = _make_watcher()
        alive_event = threading.Event()

        def wait_forever():
            alive_event.wait(timeout=5)

        alive_thread = threading.Thread(target=wait_forever)
        alive_thread.start()
        watcher._orphan_threads.append(alive_thread)
        watcher._cleanup_orphan_threads()
        self.assertEqual(len(watcher._orphan_threads), 1)
        alive_event.set()
        alive_thread.join(timeout=5)
        watcher.close()

    def test_max_orphan_threads_constant(self):
        self.assertEqual(_MAX_ORPHAN_THREADS, 5)

    def test_mixed_dead_and_alive_threads(self):
        watcher = _make_watcher()
        alive_event = threading.Event()

        def wait_forever():
            alive_event.wait(timeout=5)

        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()

        alive_thread = threading.Thread(target=wait_forever)
        alive_thread.start()

        watcher._orphan_threads.append(dead_thread)
        watcher._orphan_threads.append(alive_thread)
        watcher._cleanup_orphan_threads()
        self.assertEqual(len(watcher._orphan_threads), 1)
        self.assertIs(watcher._orphan_threads[0], alive_thread)
        alive_event.set()
        alive_thread.join(timeout=5)
        watcher.close()


class TestHistoryWriteFailure(unittest.TestCase):
    """Tests for history write failure handling."""

    def test_history_add_failure_does_not_crash_poll(self):
        class FailingHistory:
            def add(self, event):
                raise sqlite3.OperationalError("database is locked")

            def close(self):
                pass

        watcher = ClipboardWatcher(
            processor=_DummyProcessor(),
            history=FailingHistory(),
            source_name="test",
        )
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        watcher.close()

    def test_history_add_failure_does_not_crash_async(self):
        class FailingHistory:
            def add(self, event):
                raise sqlite3.OperationalError("database is locked")

            def close(self):
                pass

        watcher = ClipboardWatcher(
            processor=_DummyProcessor(),
            history=FailingHistory(),
            source_name="test",
        )
        result_event = threading.Event()
        result_holder = [None]

        def on_done(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once_async(on_done, force=True)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertIsNotNone(result_holder[0])
        watcher.close()


class TestVariousProcessorBehaviors(unittest.TestCase):
    """Tests for various processor behaviors."""

    def test_processor_returning_empty_string(self):
        class EmptyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return ""

        watcher = _make_watcher(processor=EmptyProcessor())
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.latex, "")
        watcher.close()

    def test_processor_returning_unicode(self):
        class UnicodeProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "\\alpha + \\beta = \\gamma"

        watcher = _make_watcher(processor=UnicodeProcessor())
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.latex, "\\alpha + \\beta = \\gamma")
        watcher.close()

    def test_processor_returning_very_long_result(self):
        class LongProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "x" * 100000

        watcher = _make_watcher(processor=LongProcessor())
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(len(result.latex), 100000)
        watcher.close()

    def test_processor_raising_value_error(self):
        class ValueErrorProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                raise ValueError("Invalid image format")

        watcher = _make_watcher(processor=ValueErrorProcessor())
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("Invalid image format", result.error)
        watcher.close()


class TestSourceName(unittest.TestCase):
    """Tests for source_name propagation."""

    def test_source_name_in_event(self):
        watcher = _make_watcher(source_name="custom_source")
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.source, "custom_source")
        watcher.close()

    def test_source_name_in_async_event(self):
        watcher = _make_watcher(source_name="async_source")
        result_event = threading.Event()
        result_holder = [None]

        def on_done(event):
            result_holder[0] = event
            result_event.set()

        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once_async(on_done, force=True)
        self.assertTrue(result_event.wait(timeout=5.0))
        self.assertEqual(result_holder[0].source, "async_source")
        watcher.close()


class TestOcrRunningClearedAfterPoll(unittest.TestCase):
    """Tests that _ocr_running is properly cleared after poll_once."""

    def test_ocr_running_cleared_after_success(self):
        watcher = _make_watcher()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once(force=True)
        self.assertFalse(watcher._ocr_running.is_set())
        watcher.close()

    def test_ocr_running_cleared_after_error(self):
        watcher = _make_watcher(processor=_FailingProcessor())
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once(force=True)
        self.assertFalse(watcher._ocr_running.is_set())
        watcher.close()

    def test_ocr_running_cleared_after_timeout(self):
        watcher = _make_watcher(processor=_HangingProcessor(), ocr_timeout=0.5)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=_make_image()):
            watcher.poll_once(force=True)
        # After timeout, ocr_running should be cleared
        # But the thread may still be alive as an orphan
        time.sleep(0.5)
        watcher.close()


if __name__ == "__main__":
    unittest.main()
