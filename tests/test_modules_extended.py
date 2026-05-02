from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.api_key_masking import (
    _is_masked_value,
    fill_masked_api_keys,
    hide_api_key,
    is_sensitive_key,
    restore_api_key,
    strip_api_keys,
)
from platex_client.history import HistoryStore, _truncate_field
from platex_client.models import ClipboardEvent, ClipboardImage, OcrProcessor
from platex_client.popup_manager import PopupManager
from platex_client.secrets import clear_all, get_secret, set_secret
from platex_client.watcher import ClipboardWatcher


class TestIsSensitiveKey(unittest.TestCase):
    def test_api_key(self):
        self.assertTrue(is_sensitive_key("api_key"))

    def test_glm_api_key(self):
        self.assertTrue(is_sensitive_key("glm_api_key"))

    def test_secret(self):
        self.assertTrue(is_sensitive_key("secret"))

    def test_token(self):
        self.assertTrue(is_sensitive_key("my_token"))

    def test_password(self):
        self.assertTrue(is_sensitive_key("password"))

    def test_apikey(self):
        self.assertTrue(is_sensitive_key("apikey"))

    def test_non_sensitive(self):
        self.assertFalse(is_sensitive_key("name"))
        self.assertFalse(is_sensitive_key("enabled"))
        self.assertFalse(is_sensitive_key("interval"))
        self.assertFalse(is_sensitive_key("api"))

    def test_case_insensitive(self):
        self.assertTrue(is_sensitive_key("API_KEY"))
        self.assertTrue(is_sensitive_key("My_Token"))
        self.assertTrue(is_sensitive_key("PASSWORD"))


class TestStripApiKeysExtended(unittest.TestCase):
    def test_deeply_nested(self):
        data = {"level1": {"level2": {"level3": {"api_key": "secret123"}}}}
        result = strip_api_keys(data)
        self.assertEqual(result["level1"]["level2"]["level3"]["api_key"], "********")

    def test_list_of_dicts(self):
        data = {"items": [{"api_key": "key1"}, {"token": "tok1"}]}
        result = strip_api_keys(data)
        self.assertEqual(result["items"][0]["api_key"], "********")
        self.assertEqual(result["items"][1]["token"], "********")

    def test_mixed_sensitive_and_normal(self):
        data = {"api_key": "secret", "name": "test", "interval": 1.0}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")
        self.assertEqual(result["name"], "test")
        self.assertEqual(result["interval"], 1.0)

    def test_none_value_not_masked(self):
        data = {"api_key": None}
        result = strip_api_keys(data)
        self.assertIsNone(result["api_key"])

    def test_numeric_value_not_masked(self):
        data = {"api_key": 12345}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], 12345)

    def test_empty_string_not_masked(self):
        data = {"api_key": ""}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "")

    def test_original_not_modified(self):
        data = {"api_key": "secret123"}
        result = strip_api_keys(data)
        self.assertEqual(data["api_key"], "secret123")
        self.assertEqual(result["api_key"], "********")


class TestHideApiKey(unittest.TestCase):
    def test_basic_hiding(self):
        text = "glm_api_key: sk-real-key-12345\n"
        result = hide_api_key(text)
        self.assertIn("***", result)
        self.assertNotIn("sk-real-key-12345", result)

    def test_multiple_keys(self):
        text = "glm_api_key: key1\nglm_model: model1\n"
        result = hide_api_key(text)
        self.assertNotIn("key1", result)
        self.assertIn("model1", result)

    def test_non_key_lines_preserved(self):
        text = "interval: 1.0\napi_key: secret\n"
        result = hide_api_key(text)
        self.assertIn("interval: 1.0", result)

    def test_empty_text(self):
        result = hide_api_key("")
        self.assertEqual(result, "")


class TestIsMaskedValue(unittest.TestCase):
    def test_all_stars(self):
        self.assertTrue(_is_masked_value("********"))
        self.assertTrue(_is_masked_value("***"))

    def test_prefix_with_stars(self):
        self.assertTrue(_is_masked_value("sk-1****"))

    def test_not_masked(self):
        self.assertFalse(_is_masked_value("real-key"))
        self.assertFalse(_is_masked_value("sk-12345"))
        self.assertFalse(_is_masked_value(""))

    def test_single_star(self):
        self.assertTrue(_is_masked_value("*"))


class TestRestoreApiKeyExtended(unittest.TestCase):
    def test_multiple_keys_in_same_text(self):
        edited = "glm_api_key: ********\nglm_base_url: ********\n"
        original = "glm_api_key: sk-key1\nglm_base_url: https://api.test.com\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-key1", result)
        self.assertIn("https://api.test.com", result)

    def test_mixed_masked_and_unmasked(self):
        edited = "glm_api_key: ********\nglm_model: glm-4v\n"
        original = "glm_api_key: sk-real\nglm_model: glm-4\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real", result)
        self.assertIn("glm-4v", result)

    def test_no_masked_keys(self):
        edited = "interval: 1.0\n"
        original = "interval: 0.8\n"
        result = restore_api_key(edited, original)
        self.assertIn("1.0", result)

    def test_empty_strings(self):
        result = restore_api_key("", "")
        self.assertEqual(result, "")


class TestFillMaskedApiKeysExtended(unittest.TestCase):
    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_fill_script_api_key(self):
        set_secret("GLM_API_KEY", "master-key")
        data = {
            "glm_api_key": "********",
            "scripts": {
                "my_script": {"api_key": "********"},
            },
        }
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "master-key")
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "master-key")

    def test_fill_script_with_script_specific_key(self):
        set_secret("GLM_API_KEY", "master-key")
        set_secret("PLATEX_API_KEY_MY_SCRIPT", "script-specific-key")
        data = {
            "scripts": {
                "my_script": {"api_key": "********"},
            },
        }
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "script-specific-key")

    def test_fill_non_masked_script_key_unchanged(self):
        data = {
            "scripts": {
                "my_script": {"api_key": "actual-key"},
            },
        }
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "actual-key")

    def test_fill_scripts_not_dict(self):
        data = {"scripts": "not_a_dict"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"], "not_a_dict")

    def test_fill_script_entry_not_dict(self):
        data = {"scripts": {"my_script": "not_a_dict"}}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"], "not_a_dict")


class TestHistoryStoreEnsureUtc(unittest.TestCase):
    def test_naive_datetime_gets_utc(self):
        dt = datetime(2024, 1, 1, 12, 0, 0)
        result = HistoryStore._ensure_utc(dt)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_utc_datetime_unchanged(self):
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = HistoryStore._ensure_utc(dt)
        self.assertEqual(result, dt)

    def test_non_utc_datetime_converted(self):
        from datetime import timedelta
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=8)))
        result = HistoryStore._ensure_utc(dt)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.hour, 4)


class TestHistoryStoreAddAfterClose(unittest.TestCase):
    def test_add_after_close_logs_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            store.close()
            event = ClipboardEvent(
                created_at=datetime.now(timezone.utc),
                image_hash="after_close",
                image_width=100,
                image_height=100,
                latex="x^2",
                source="test",
                status="ok",
                error=None,
            )
            store.add(event)
            store.close()


class TestHistoryStoreListRecent(unittest.TestCase):
    def test_list_recent_with_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with HistoryStore(db_path) as store:
                for i in range(10):
                    event = ClipboardEvent(
                        created_at=datetime.now(timezone.utc),
                        image_hash=f"hash_{i}",
                        image_width=100,
                        image_height=100,
                        latex=f"x^{i}",
                        source="test",
                        status="ok",
                        error=None,
                    )
                    store.add(event)
                recent = store.list_recent(limit=5)
                self.assertEqual(len(recent), 5)

    def test_list_recent_after_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            store.close()
            result = store.list_recent()
            self.assertEqual(result, [])


class TestHistoryStoreTruncateField(unittest.TestCase):
    def test_short_value_unchanged(self):
        self.assertEqual(_truncate_field("short", "image_hash"), "short")

    def test_exact_limit_unchanged(self):
        val = "x" * 128
        self.assertEqual(_truncate_field(val, "image_hash"), val)

    def test_over_limit_truncated(self):
        val = "x" * 200
        result = _truncate_field(val, "image_hash")
        self.assertLessEqual(len(result), 128)
        self.assertTrue(result.endswith("..."))

    def test_unknown_field_unchanged(self):
        val = "x" * 1000
        result = _truncate_field(val, "unknown_field")
        self.assertEqual(result, val)


class TestClipboardImageModel(unittest.TestCase):
    def test_default_fingerprint(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100)
        self.assertEqual(img.fingerprint, "")

    def test_custom_fingerprint(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100, fingerprint="abc123")
        self.assertEqual(img.fingerprint, "abc123")

    def test_pil_image_none_initially(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100)
        self.assertIsNone(img._pil_image)


class TestOcrProcessorBase(unittest.TestCase):
    def test_process_image_raises(self):
        proc = OcrProcessor()
        with self.assertRaises(NotImplementedError):
            proc.process_image(b"fake", {})


class TestPopupManagerExtended(unittest.TestCase):
    def test_show_popup_default_timeout(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content")
        self.assertFalse(pm.popup_queue.empty())
        _, _, timeout = pm.popup_queue.get_nowait()
        self.assertEqual(timeout, 12000)

    def test_show_popup_custom_timeout(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content", timeout_ms=5000)
        _, _, timeout = pm.popup_queue.get_nowait()
        self.assertEqual(timeout, 5000)

    def test_open_panel_emits_event(self):
        pm = PopupManager()
        from platex_client.events import ShowPanelEvent
        received = []
        pm._bus.subscribe(ShowPanelEvent, lambda e: received.append(e))
        pm.open_panel()
        self.assertEqual(len(received), 1)

    def test_request_shutdown_emits_event(self):
        pm = PopupManager()
        from platex_client.events import ShutdownRequestEvent
        received = []
        pm._bus.subscribe(ShutdownRequestEvent, lambda e: received.append(e))
        pm.request_shutdown()
        self.assertEqual(len(received), 1)

    def test_subscribe_unsubscribe_ocr_events(self):
        pm = PopupManager()
        pm.subscribe_ocr_events()
        self.assertGreater(pm._bus.subscriber_count(OcrSuccessEvent), 0)
        pm.unsubscribe_ocr_events()

    def test_ocr_success_triggers_popup(self):
        pm = PopupManager()
        pm._on_ocr_success(OcrSuccessEvent(latex="x^2", image_hash="abc"))
        self.assertFalse(pm.popup_queue.empty())


class TestClipboardWatcherForcePoll(unittest.TestCase):
    def _make_watcher(self, processor=None, history=None):
        if processor is None:
            class DummyProcessor(OcrProcessor):
                def process_image(self, image_bytes, context=None):
                    return "test"

            processor = DummyProcessor()

        if history is None:
            temp_dir = tempfile.mkdtemp()
            db_path = Path(temp_dir) / "test.sqlite3"
            history = HistoryStore(db_path)

        return ClipboardWatcher(
            processor=processor,
            history=history,
            source_name="test",
        )

    def test_force_poll_ignores_hash(self):
        watcher = self._make_watcher()
        watcher.last_image_hash = "existing_hash"
        from platex_client.models import ClipboardImage
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        from platex_client.clipboard import image_hash
        fake_hash = image_hash(b"fake")
        watcher.last_image_hash = fake_hash

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once(force=True)
        self.assertIsNotNone(result)
        watcher.close()

    def test_same_hash_skipped_without_force(self):
        watcher = self._make_watcher()
        from platex_client.models import ClipboardImage
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        from platex_client.clipboard import image_hash
        watcher.last_image_hash = image_hash(b"fake")

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once(force=False)
        self.assertIsNone(result)
        watcher.close()


class TestClipboardWatcherAsyncPoll(unittest.TestCase):
    def test_async_poll_no_image(self):
        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )

        with patch("platex_client.watcher.grab_image_clipboard", return_value=None):
            result = watcher.poll_once_async(lambda e: None)
        self.assertFalse(result)
        watcher.close()

    def test_async_poll_while_paused(self):
        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )
        watcher.set_publishing(True)

        result = watcher.poll_once_async(lambda e: None)
        self.assertFalse(result)
        watcher.close()

    def test_async_poll_while_ocr_running(self):
        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )
        watcher._ocr_running.set()

        result = watcher.poll_once_async(lambda e: None)
        self.assertFalse(result)
        watcher._ocr_running.clear()
        watcher.close()


class TestSecretsGetAllKeys(unittest.TestCase):
    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_empty(self):
        self.assertEqual(get_all_keys(), [])

    def test_after_set(self):
        set_secret("KEY1", "val1")
        set_secret("KEY2", "val2")
        keys = get_all_keys()
        self.assertIn("KEY1", keys)
        self.assertIn("KEY2", keys)

    def test_after_delete(self):
        set_secret("KEY1", "val1")
        set_secret("KEY2", "val2")
        from platex_client.secrets import delete_secret
        delete_secret("KEY1")
        keys = get_all_keys()
        self.assertNotIn("KEY1", keys)
        self.assertIn("KEY2", keys)


if __name__ == "__main__":
    unittest.main()
