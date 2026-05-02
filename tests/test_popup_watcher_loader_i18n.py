from __future__ import annotations

import os
import queue
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.i18n import (
    available_languages,
    get_current_language,
    initialize,
    on_language_changed,
    remove_language_callback,
    switch_language,
    t,
)
from platex_client.loader import LegacyProcessor, OcrProcessorAdapter, load_script_processor
from platex_client.models import ClipboardEvent, ClipboardImage, OcrProcessor
from platex_client.popup_manager import PopupManager
from platex_client.watcher import ClipboardWatcher


class TestPopupManagerComprehensive(unittest.TestCase):
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
        self.assertEqual(item[0], "Title")
        self.assertEqual(item[1], "Content")
        self.assertEqual(item[2], 12000)

    def test_show_popup_custom_timeout(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content", timeout_ms=3000)
        item = pm.popup_queue.get_nowait()
        self.assertEqual(item[2], 3000)

    def test_open_panel_not_shutdown(self):
        pm = PopupManager()
        pm.open_panel()
        self.assertFalse(pm.panel_queue.empty())

    def test_open_panel_when_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.open_panel()
        self.assertTrue(pm.panel_queue.empty() or pm.panel_queue.get_nowait() is None)

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

    def test_subscribe_ocr_events(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()

    def test_unsubscribe_ocr_events(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        pm.unsubscribe_ocr_events()

    def test_on_ocr_success(self):
        pm = PopupManager()
        from platex_client.events import OcrSuccessEvent
        pm._on_ocr_success(OcrSuccessEvent(latex="x^2"))
        self.assertFalse(pm.popup_queue.empty())


class TestClipboardWatcherComprehensive(unittest.TestCase):
    def _make_watcher(self, processor=None, history=None):
        if processor is None:
            class DummyProcessor(OcrProcessor):
                def process_image(self, image_bytes, context=None):
                    return "test"

            processor = DummyProcessor()

        if history is None:
            temp_dir = tempfile.mkdtemp()
            from platex_client.history import HistoryStore
            db_path = Path(temp_dir) / "test.sqlite3"
            history = HistoryStore(db_path)

        return ClipboardWatcher(
            processor=processor,
            history=history,
            source_name="test",
        )

    def test_poll_when_no_clipboard_image(self):
        watcher = self._make_watcher()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=None):
            result = watcher.poll_once()
        self.assertIsNone(result)
        watcher.close()

    def test_poll_while_ocr_running(self):
        watcher = self._make_watcher()
        watcher._ocr_running.set()
        result = watcher.poll_once()
        self.assertIsNone(result)
        watcher._ocr_running.clear()
        watcher.close()

    def test_set_publishing_blocks_polling(self):
        watcher = self._make_watcher()
        watcher.set_publishing(True)
        self.assertTrue(watcher._paused.is_set())
        result = watcher.poll_once()
        self.assertIsNone(result)
        watcher.set_publishing(False)
        watcher.close()

    def test_set_publishing_false_allows_polling(self):
        watcher = self._make_watcher()
        watcher.set_publishing(False)
        self.assertFalse(watcher._paused.is_set())
        watcher.close()

    def test_ocr_timeout_handling(self):
        class HangingProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                time.sleep(10)
                return "never"

        temp_dir = tempfile.mkdtemp()
        from platex_client.history import HistoryStore
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=HangingProcessor(),
            history=history,
            source_name="test",
            ocr_timeout=0.5,
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("timed out", result.error)
        watcher.close()

    def test_ocr_exception_handling(self):
        class FailingProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                raise RuntimeError("OCR engine failure")

        temp_dir = tempfile.mkdtemp()
        from platex_client.history import HistoryStore
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=FailingProcessor(),
            history=history,
            source_name="test",
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("OCR engine failure", result.error)
        watcher.close()

    def test_ocr_success_result(self):
        class SuccessProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "x^2 + y^2"

        temp_dir = tempfile.mkdtemp()
        from platex_client.history import HistoryStore
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=SuccessProcessor(),
            history=history,
            source_name="test",
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.latex, "x^2 + y^2")
        watcher.close()

    def test_history_write_failure_does_not_crash(self):
        class FailingHistory:
            def add(self, event):
                raise RuntimeError("DB locked")

            def close(self):
                pass

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=FailingHistory(),
            source_name="test",
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        watcher.close()

    def test_close_safe_when_history_is_none(self):
        temp_dir = tempfile.mkdtemp()
        from platex_client.history import HistoryStore
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )
        watcher.history = None
        watcher.close()
        history.close()

    def test_cleanup_orphan_threads(self):
        temp_dir = tempfile.mkdtemp()
        from platex_client.history import HistoryStore
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()
        watcher._orphan_threads.append(dead_thread)
        watcher._cleanup_orphan_threads()
        self.assertEqual(len(watcher._orphan_threads), 0)
        watcher.close()

    def test_duplicate_image_skipped(self):
        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        temp_dir = tempfile.mkdtemp()
        from platex_client.history import HistoryStore
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result1 = watcher.poll_once()
            result2 = watcher.poll_once()
        self.assertIsNotNone(result1)
        self.assertIsNone(result2)
        watcher.close()

    def test_force_poll_ignores_duplicate(self):
        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        temp_dir = tempfile.mkdtemp()
        from platex_client.history import HistoryStore
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result1 = watcher.poll_once()
            result2 = watcher.poll_once(force=True)
        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)
        watcher.close()


class TestLoaderComprehensive(unittest.TestCase):
    def test_load_script_returning_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "string_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return r'\\alpha + \\beta'\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            result = processor.process_image(b"test", {})
            self.assertEqual(result, r"\alpha + \beta")

    def test_load_script_returning_dict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dict_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n"
                "    return {'latex': r'x^2 + y^2'}\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            result = processor.process_image(b"test", {})
            self.assertEqual(result, "x^2 + y^2")

    def test_load_script_returning_unsupported_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "bad_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 42\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError):
                processor.process_image(b"test", {})

    def test_load_script_returning_empty_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "empty_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return '  '\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError):
                processor.process_image(b"test", {})

    def test_load_script_no_entry_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "noop.py"
            script_path.write_text("x = 42\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_script_processor(script_path)

    def test_load_script_with_create_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "newstyle.py"
            script_path.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'my_script'\n"
                "    @property\n"
                "    def display_name(self): return 'My Script'\n"
                "    @property\n"
                "    def description(self): return 'Test'\n"
                "    def has_ocr_capability(self): return True\n"
                "    def process_image(self, image_bytes, context=None): return 'result'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            self.assertIsInstance(processor, OcrProcessorAdapter)
            result = processor.process_image(b"test", {})
            self.assertEqual(result, "result")

    def test_load_script_nonexistent(self):
        with self.assertRaises(FileNotFoundError):
            load_script_processor(Path("/nonexistent/script.py"))


class TestI18nComprehensive(unittest.TestCase):
    def test_initialize_with_en(self):
        initialize("en")
        self.assertEqual(get_current_language(), "en")

    def test_initialize_with_invalid_language(self):
        initialize("nonexistent")
        self.assertEqual(get_current_language(), "en")

    def test_t_returns_key_for_missing_translation(self):
        initialize("en")
        result = t("nonexistent.key.12345")
        self.assertEqual(result, "nonexistent.key.12345")

    def test_t_with_format_kwargs(self):
        initialize("en")
        result = t("nonexistent.key.{name}", name="test")
        self.assertIn("test", result)

    def test_available_languages(self):
        langs = available_languages()
        self.assertIsInstance(langs, list)
        for code, name in langs:
            self.assertIsInstance(code, str)
            self.assertIsInstance(name, str)

    def test_switch_language(self):
        initialize("en")
        switch_language("zh-cn")
        self.assertEqual(get_current_language(), "zh-cn")

    def test_switch_to_invalid_language_keeps_current(self):
        initialize("en")
        switch_language("invalid")
        self.assertEqual(get_current_language(), "en")

    def test_switch_to_same_language_noop(self):
        initialize("en")
        switch_language("en")
        self.assertEqual(get_current_language(), "en")

    def test_on_language_changed_callback(self):
        initialize("en")
        received = []
        on_language_changed(lambda lang: received.append(lang))
        switch_language("zh-cn")
        self.assertTrue(len(received) > 0)
        self.assertEqual(received[-1], "zh-cn")

    def test_remove_language_callback(self):
        initialize("en")
        received = []
        cb = lambda lang: received.append(lang)
        on_language_changed(cb)
        remove_language_callback(cb)
        switch_language("zh-cn")
        self.assertEqual(len(received), 0)


class TestModelsComprehensive(unittest.TestCase):
    def test_clipboard_event_creation(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="abc123",
            image_width=120,
            image_height=80,
            latex=r"x^2+y^2=z^2",
            source="test",
            status="ok",
            error=None,
        )
        self.assertEqual(event.image_hash, "abc123")
        self.assertEqual(event.latex, r"x^2+y^2=z^2")
        self.assertEqual(event.status, "ok")
        self.assertIsNone(event.error)

    def test_clipboard_event_with_error(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="err",
            image_width=0,
            image_height=0,
            latex="",
            source="test",
            status="error",
            error="timeout",
        )
        self.assertEqual(event.status, "error")
        self.assertEqual(event.error, "timeout")

    def test_clipboard_image_creation(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100)
        self.assertEqual(img.image_bytes, b"fake")
        self.assertEqual(img.width, 100)
        self.assertEqual(img.height, 100)
        self.assertEqual(img.fingerprint, "")

    def test_clipboard_image_with_fingerprint(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100, fingerprint="abc123")
        self.assertEqual(img.fingerprint, "abc123")

    def test_ocr_processor_not_implemented(self):
        processor = OcrProcessor()
        with self.assertRaises(NotImplementedError):
            processor.process_image(b"test")


if __name__ == "__main__":
    unittest.main()
