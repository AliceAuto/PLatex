from __future__ import annotations

import gc
import logging
import os
import queue
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import weakref
from datetime import datetime, timezone
from io import BytesIO
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
from platex_client.app_config import (
    AppConfig as AppConfigV2,
    app_config_to_dict,
    candidate_config_paths,
    load_file_payload,
    parse_bool as parse_bool_v2,
    parse_payload_to_app_config,
    _validate_config_path as validate_config_path_v2,
)
from platex_client.app_state import AppState, StateMachine
from platex_client.config import AppConfig, ConfigStore, _parse_bool, load_config
from platex_client.config_manager import (
    ConfigManager,
    _ALLOWED_GENERAL_KEYS,
    _MAX_IMPORT_FILE_SIZE,
    _apply_migrations,
    _cleanup_old_backups,
    backup_config,
    config_file_path,
    deep_merge,
    set_config_dir,
)
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
from platex_client.history import (
    _MAX_FIELD_LENGTHS,
    _MAX_HISTORY_ROWS,
    _VACUUM_CHECK_INTERVAL,
    HistoryStore,
    _truncate_field,
)
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
from platex_client.script_base import ScriptBase, TrayMenuItem
from platex_client.script_context import (
    ClipboardAPI,
    ConfigAPI,
    HistoryAPI,
    HotkeyAPI,
    LoggerAPI,
    MouseAPI,
    NotificationAPI,
    SchedulerAPI,
    ScriptContext,
    WindowAPI,
    _ScheduledTask,
)
from platex_client.script_registry import ScriptRegistry
from platex_client.script_safety import (
    _BLOCKED_PATTERNS,
    _DANGEROUS_PATTERNS,
    _MAX_SCRIPT_FILE_SIZE,
    _check_dangerous_patterns,
    _extract_legacy_result,
    _load_script_module,
    check_blocked_patterns,
    scan_script_source,
    validate_script_path,
)
from platex_client.secrets import (
    clear_all,
    delete_secret,
    get_all_keys,
    get_secret,
    has_secret,
    set_secret,
)
from platex_client.watcher import ClipboardWatcher


class TestClipboardEventModel(unittest.TestCase):
    def test_create_basic_event(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="abc",
            image_width=100,
            image_height=200,
            latex="x^2",
            source="test",
            status="ok",
        )
        self.assertEqual(event.image_hash, "abc")
        self.assertIsNone(event.error)

    def test_create_event_with_error(self):
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

    def test_event_is_mutable_dataclass(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="abc",
            image_width=100,
            image_height=100,
            latex="x",
            source="test",
            status="ok",
        )
        event.latex = "y"
        self.assertEqual(event.latex, "y")

    def test_event_with_unicode_latex(self):
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="uni",
            image_width=100,
            image_height=100,
            latex=r"\alpha + \beta = \gamma",
            source="test",
            status="ok",
        )
        self.assertIn(r"\alpha", event.latex)

    def test_event_with_very_long_latex(self):
        long_latex = "x" * 10000
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="long",
            image_width=100,
            image_height=100,
            latex=long_latex,
            source="test",
            status="ok",
        )
        self.assertEqual(len(event.latex), 10000)

    def test_event_with_multiline_latex(self):
        latex = "\\begin{align}\nx^2 + y^2 = z^2\n\\end{align}"
        event = ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="ml",
            image_width=100,
            image_height=100,
            latex=latex,
            source="test",
            status="ok",
        )
        self.assertIn("\n", event.latex)


class TestClipboardImageModel(unittest.TestCase):
    def test_create_with_bytes(self):
        img = ClipboardImage(image_bytes=b"fake", width=100, height=200)
        self.assertEqual(img.image_bytes, b"fake")
        self.assertEqual(img.width, 100)
        self.assertEqual(img.height, 200)
        self.assertEqual(img.fingerprint, "")

    def test_create_with_fingerprint(self):
        img = ClipboardImage(image_bytes=b"fake", width=10, height=10, fingerprint="fp123")
        self.assertEqual(img.fingerprint, "fp123")

    def test_default_pil_image_is_none(self):
        img = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        self.assertIsNone(img._pil_image)

    def test_get_pil_image_from_bytes(self):
        from PIL import Image
        buf = BytesIO()
        img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        ci = ClipboardImage(image_bytes=image_bytes, width=10, height=10)
        pil = ci.get_pil_image()
        self.assertIsNotNone(pil)
        self.assertEqual(pil.size, (10, 10))

    def test_get_pil_image_caches(self):
        from PIL import Image
        buf = BytesIO()
        img = Image.new("RGBA", (10, 10))
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        ci = ClipboardImage(image_bytes=image_bytes, width=10, height=10)
        first = ci.get_pil_image()
        ci._pil_image = first
        second = ci.get_pil_image()
        self.assertIs(first, second)


class TestOcrProcessorAbstract(unittest.TestCase):
    def test_process_image_raises_not_implemented(self):
        proc = OcrProcessor()
        with self.assertRaises(NotImplementedError):
            proc.process_image(b"fake", {})


class TestTrayMenuItem(unittest.TestCase):
    def test_default_values(self):
        item = TrayMenuItem()
        self.assertEqual(item.label, "")
        self.assertIsNone(item.action)
        self.assertIsNone(item.items)
        self.assertIsNone(item.checked)
        self.assertTrue(item.enabled)
        self.assertFalse(item.separator)

    def test_with_label_and_action(self):
        called = []
        item = TrayMenuItem(label="Test", action=lambda: called.append(1))
        self.assertEqual(item.label, "Test")
        item.action()
        self.assertEqual(called, [1])

    def test_callable_label(self):
        item = TrayMenuItem(label=lambda: "Dynamic")
        self.assertTrue(callable(item.label))

    def test_callable_checked(self):
        item = TrayMenuItem(checked=lambda: True)
        self.assertTrue(callable(item.checked))

    def test_callable_enabled(self):
        item = TrayMenuItem(enabled=lambda: False)
        self.assertTrue(callable(item.enabled))

    def test_separator_item(self):
        item = TrayMenuItem(separator=True)
        self.assertTrue(item.separator)

    def test_nested_items(self):
        sub = TrayMenuItem(label="Sub")
        item = TrayMenuItem(label="Parent", items=[sub])
        self.assertEqual(len(item.items), 1)
        self.assertEqual(item.items[0].label, "Sub")


class TestScriptBaseExtended(unittest.TestCase):
    def _make_script(self):
        class TestScript(ScriptBase):
            @property
            def name(self):
                return "test"

            @property
            def display_name(self):
                return "Test"

            @property
            def description(self):
                return "Test script"

        return TestScript()

    def _make_ocr_script(self):
        class OcrScript(ScriptBase):
            @property
            def name(self):
                return "ocr_test"

            @property
            def display_name(self):
                return "OCR Test"

            @property
            def description(self):
                return "OCR test script"

            def has_ocr_capability(self):
                return True

            def process_image(self, image_bytes, context=None):
                return r"\alpha"

        return OcrScript()

    def test_context_default_none(self):
        self.assertIsNone(self._make_script().context)

    def test_on_context_ready(self):
        script = self._make_script()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        self.assertIs(script.context, ctx)

    def test_create_settings_widget_returns_none(self):
        self.assertIsNone(self._make_script().create_settings_widget())

    def test_get_hotkey_bindings_default_empty(self):
        self.assertEqual(self._make_script().get_hotkey_bindings(), {})

    def test_on_hotkey_does_nothing(self):
        self._make_script().on_hotkey("test")

    def test_passthrough_hotkeys_default_false(self):
        self.assertFalse(self._make_script().passthrough_hotkeys)

    def test_activate_does_nothing(self):
        self._make_script().activate()

    def test_deactivate_clears_context(self):
        script = self._make_script()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        script.deactivate()
        self.assertIsNone(script.context)

    def test_deactivate_calls_context_shutdown(self):
        script = self._make_script()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        script.deactivate()
        ctx.shutdown.assert_called_once()

    def test_deactivate_handles_shutdown_exception(self):
        script = self._make_script()
        ctx = MagicMock()
        ctx.shutdown.side_effect = RuntimeError("boom")
        script.on_context_ready(ctx)
        script.deactivate()
        self.assertIsNone(script.context)

    def test_load_config_does_nothing(self):
        self._make_script().load_config({"key": "value"})

    def test_save_config_returns_empty(self):
        self.assertEqual(self._make_script().save_config(), {})

    def test_has_ocr_capability_default_false(self):
        self.assertFalse(self._make_script().has_ocr_capability())

    def test_process_image_without_capability_raises(self):
        with self.assertRaises(RuntimeError):
            self._make_script().process_image(b"fake", {})

    def test_process_image_with_capability_not_implemented(self):
        script = self._make_ocr_script()
        self.assertTrue(script.has_ocr_capability())
        result = script.process_image(b"fake", {})
        self.assertEqual(result, r"\alpha")

    def test_get_tray_menu_items_default_empty(self):
        self.assertEqual(self._make_script().get_tray_menu_items(), [])

    def test_test_connection_default_ok(self):
        ok, msg = self._make_script().test_connection()
        self.assertTrue(ok)
        self.assertEqual(msg, "OK")

    def test_set_tray_action_callback(self):
        script = self._make_script()
        cb = MagicMock()
        script.set_tray_action_callback(cb)
        self.assertIs(script._tray_action_callback, cb)

    def test_set_hotkeys_changed_callback(self):
        script = self._make_script()
        called = threading.Event()
        script.set_hotkeys_changed_callback(called.set)
        script._notify_hotkeys_changed()
        self.assertTrue(called.is_set())

    def test_notify_hotkeys_changed_no_callback(self):
        self._make_script()._notify_hotkeys_changed()

    def test_notify_hotkeys_changed_callback_exception(self):
        script = self._make_script()
        def bad_cb():
            raise RuntimeError("callback error")
        script.set_hotkeys_changed_callback(bad_cb)
        script._notify_hotkeys_changed()

    def test_import_config(self):
        script = self._make_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("key1: value1\nkey2: 42\n", encoding="utf-8")
            result = script.import_config(cfg_path)
            self.assertEqual(result["key1"], "value1")
            self.assertEqual(result["key2"], 42)

    def test_import_config_path_traversal(self):
        script = self._make_script()
        with self.assertRaises(ValueError):
            script.import_config(Path("../../etc/config.yaml"))

    def test_import_config_nonexistent_file(self):
        script = self._make_script()
        with self.assertRaises(FileNotFoundError):
            script.import_config(Path("/nonexistent/config.yaml"))

    def test_import_config_empty_file(self):
        script = self._make_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "empty.yaml"
            cfg_path.write_text("---\n", encoding="utf-8")
            result = script.import_config(cfg_path)
            self.assertEqual(result, {})

    def test_import_config_non_dict_file(self):
        script = self._make_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "list.yaml"
            cfg_path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                script.import_config(cfg_path)

    def test_export_config(self):
        script = self._make_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "export.yaml"
            script.export_config(cfg_path)
            self.assertTrue(cfg_path.exists())
            import yaml
            data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            self.assertEqual(data["__script_name__"], "test")

    def test_export_config_path_traversal(self):
        script = self._make_script()
        with self.assertRaises(ValueError):
            script.export_config(Path("../../tmp/export.yaml"))

    def test_validate_config_path_rejects_dotdot(self):
        with self.assertRaises(ValueError):
            ScriptBase._validate_config_path(Path("../../etc/passwd"))

    def test_validate_config_path_normal(self):
        result = ScriptBase._validate_config_path(Path("normal/path"))
        self.assertIsInstance(result, Path)


class TestScriptContextAPIs(unittest.TestCase):
    def test_clipboard_api(self):
        read_text_fn = MagicMock(return_value="hello")
        write_text_fn = MagicMock()
        read_image_fn = MagicMock(return_value=None)
        api = ClipboardAPI(
            read_text_fn=read_text_fn,
            write_text_fn=write_text_fn,
            read_image_fn=read_image_fn,
        )
        self.assertEqual(api.read_text(), "hello")
        api.write_text("world")
        write_text_fn.assert_called_with("world")
        self.assertIsNone(api.read_image())

    def test_hotkey_api(self):
        register_fn = MagicMock(return_value=True)
        unregister_fn = MagicMock()
        api = HotkeyAPI(register_fn=register_fn, unregister_fn=unregister_fn)
        self.assertTrue(api.register("Ctrl+A", lambda: None))
        api.unregister("Ctrl+A")
        unregister_fn.assert_called_with("Ctrl+A")

    def test_notification_api(self):
        show_fn = MagicMock()
        show_ocr_fn = MagicMock()
        api = NotificationAPI(show_fn=show_fn, show_ocr_fn=show_ocr_fn)
        api.show("Title", "Message", timeout_ms=3000)
        show_fn.assert_called_with("Title", "Message", 3000)
        api.show_ocr_result("x^2", timeout_ms=5000)
        show_ocr_fn.assert_called_with("x^2", 5000)

    def test_window_api(self):
        api = WindowAPI(get_foreground_title_fn=lambda: "Test Window")
        self.assertEqual(api.get_foreground_title(), "Test Window")

    def test_mouse_api(self):
        click_fn = MagicMock()
        api = MouseAPI(click_fn=click_fn)
        api.click(100, 200, button="right")
        click_fn.assert_called_with(100, 200, "right")

    def test_history_api(self):
        latest_fn = MagicMock(return_value=None)
        list_recent_fn = MagicMock(return_value=[])
        api = HistoryAPI(latest_fn=latest_fn, list_recent_fn=list_recent_fn)
        self.assertIsNone(api.latest())
        self.assertEqual(api.list_recent(5), [])

    def test_config_api(self):
        get_fn = MagicMock(return_value="default_val")
        set_fn = MagicMock()
        save_fn = MagicMock()
        get_all_fn = MagicMock(return_value={"key": "val"})
        api = ConfigAPI(get_fn=get_fn, set_fn=set_fn, save_fn=save_fn, get_all_fn=get_all_fn)
        self.assertEqual(api.get("key", "default_val"), "default_val")
        api.set("key", "new_val")
        api.save()
        api.get_all()
        set_fn.assert_called_with("key", "new_val")
        save_fn.assert_called_once()
        get_all_fn.assert_called_once()

    def test_logger_api(self):
        api = LoggerAPI()
        logger = api.get("test_script")
        self.assertIsInstance(logger, logging.Logger)
        self.assertIn("platex.script.test_script", logger.name)

    def test_script_context_shutdown(self):
        ctx = ScriptContext(
            clipboard=MagicMock(),
            hotkeys=MagicMock(),
            notifications=MagicMock(),
            windows=MagicMock(),
            mouse=MagicMock(),
            scheduler=MagicMock(),
            history=MagicMock(),
            config=MagicMock(),
            logger=LoggerAPI(),
        )
        ctx.shutdown()
        ctx.scheduler.cancel_all.assert_called_once()


class TestScheduledTask(unittest.TestCase):
    def test_cancel_sets_event(self):
        task = _ScheduledTask(None)
        self.assertFalse(task.is_cancelled)
        task.cancel()
        self.assertTrue(task.is_cancelled)

    def test_set_timer_after_cancel_cancels_timer(self):
        task = _ScheduledTask(None)
        task.cancel()
        timer = threading.Timer(10, lambda: None)
        task.set_timer(timer)
        self.assertTrue(task.is_cancelled)

    def test_set_timer_when_active(self):
        task = _ScheduledTask(None)
        timer = threading.Timer(10, lambda: None)
        task.set_timer(timer)
        self.assertFalse(task.is_cancelled)
        task.cancel()


class TestSchedulerAPIExtended(unittest.TestCase):
    def test_schedule_once_fires(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        scheduler.schedule_once(0.05, fired.set)
        self.assertTrue(fired.wait(timeout=2.0))
        scheduler.cancel_all()

    def test_schedule_repeating_fires_multiple(self):
        scheduler = SchedulerAPI()
        count = {"value": 0}
        done = threading.Event()

        def increment():
            count["value"] += 1
            if count["value"] >= 3:
                done.set()

        task = scheduler.schedule_repeating(0.05, increment)
        self.assertTrue(done.wait(timeout=5.0))
        self.assertGreaterEqual(count["value"], 3)
        task.cancel()
        scheduler.cancel_all()

    def test_cancel_prevents_execution(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        task = scheduler.schedule_once(0.5, fired.set)
        task.cancel()
        time.sleep(0.8)
        self.assertFalse(fired.is_set())
        scheduler.cancel_all()

    def test_cancel_all_stops_all(self):
        scheduler = SchedulerAPI()
        f1 = threading.Event()
        f2 = threading.Event()
        scheduler.schedule_once(0.3, f1.set)
        scheduler.schedule_once(0.3, f2.set)
        scheduler.cancel_all()
        time.sleep(0.5)
        self.assertFalse(f1.is_set())
        self.assertFalse(f2.is_set())

    def test_max_task_limit(self):
        scheduler = SchedulerAPI()
        tasks = []
        try:
            for _ in range(64):
                tasks.append(scheduler.schedule_once(10.0, lambda: None))
            with self.assertRaises(RuntimeError):
                scheduler.schedule_once(10.0, lambda: None)
        finally:
            scheduler.cancel_all()

    def test_callback_exception_does_not_break(self):
        scheduler = SchedulerAPI()
        good = threading.Event()

        def bad():
            raise RuntimeError("fail")

        scheduler.schedule_once(0.05, bad)
        scheduler.schedule_once(0.1, good.set)
        self.assertTrue(good.wait(timeout=3.0))
        scheduler.cancel_all()

    def test_double_cancel_is_safe(self):
        scheduler = SchedulerAPI()
        task = scheduler.schedule_once(10.0, lambda: None)
        task.cancel()
        task.cancel()
        scheduler.cancel_all()

    def test_cancel_already_fired(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        task = scheduler.schedule_once(0.05, fired.set)
        self.assertTrue(fired.wait(timeout=2.0))
        task.cancel()
        scheduler.cancel_all()

    def test_repeating_exception_continues(self):
        scheduler = SchedulerAPI()
        count = {"value": 0}
        done = threading.Event()

        def failing():
            count["value"] += 1
            if count["value"] == 1:
                raise RuntimeError("first fail")
            if count["value"] >= 3:
                done.set()

        task = scheduler.schedule_repeating(0.05, failing)
        self.assertTrue(done.wait(timeout=5.0))
        self.assertGreaterEqual(count["value"], 3)
        task.cancel()
        scheduler.cancel_all()

    def test_min_delay_clamped(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        scheduler.schedule_once(0.001, fired.set)
        self.assertTrue(fired.wait(timeout=2.0))
        scheduler.cancel_all()


class TestSecretsExtended(unittest.TestCase):
    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_set_and_get(self):
        set_secret("KEY", "value")
        self.assertEqual(get_secret("KEY"), "value")

    def test_get_default(self):
        self.assertEqual(get_secret("NONEXISTENT", "fallback"), "fallback")

    def test_get_default_empty(self):
        self.assertEqual(get_secret("NONEXISTENT"), "")

    def test_has_secret(self):
        self.assertFalse(has_secret("KEY"))
        set_secret("KEY", "val")
        self.assertTrue(has_secret("KEY"))

    def test_delete_secret(self):
        set_secret("KEY", "val")
        delete_secret("KEY")
        self.assertFalse(has_secret("KEY"))

    def test_delete_nonexistent(self):
        delete_secret("NONEXISTENT")

    def test_clear_all(self):
        set_secret("A", "1")
        set_secret("B", "2")
        clear_all()
        self.assertFalse(has_secret("A"))
        self.assertFalse(has_secret("B"))

    def test_clear_all_when_empty(self):
        clear_all()

    def test_overwrite_secret(self):
        set_secret("KEY", "old")
        set_secret("KEY", "new")
        self.assertEqual(get_secret("KEY"), "new")

    def test_unicode_values(self):
        set_secret("UNI", "中文密钥 🔑")
        self.assertEqual(get_secret("UNI"), "中文密钥 🔑")

    def test_empty_value(self):
        set_secret("EMPTY", "")
        self.assertTrue(has_secret("EMPTY"))
        self.assertEqual(get_secret("EMPTY"), "")

    def test_get_all_keys(self):
        set_secret("A", "1")
        set_secret("B", "2")
        keys = get_all_keys()
        self.assertIn("A", keys)
        self.assertIn("B", keys)

    def test_get_all_keys_empty(self):
        self.assertEqual(get_all_keys(), [])

    def test_concurrent_access(self):
        errors = []

        def writer():
            try:
                for i in range(100):
                    set_secret("KEY", f"value_{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    get_secret("KEY")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_long_value(self):
        long_val = "x" * 10000
        set_secret("LONG", long_val)
        self.assertEqual(get_secret("LONG"), long_val)

    def test_special_chars_in_key(self):
        set_secret("key.with.dots", "val")
        self.assertEqual(get_secret("key.with.dots"), "val")


class TestAppConfigExtended(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_default_values(self):
        cfg = AppConfig()
        self.assertIsNone(cfg.db_path)
        self.assertIsNone(cfg.script)
        self.assertIsNone(cfg.log_file)
        self.assertEqual(cfg.interval, 0.8)
        self.assertFalse(cfg.isolate_mode)
        self.assertIsNone(cfg.glm_api_key)
        self.assertIsNone(cfg.glm_model)
        self.assertIsNone(cfg.glm_base_url)
        self.assertFalse(cfg.auto_start)
        self.assertEqual(cfg.ui_language, "en")
        self.assertEqual(cfg.language_pack, "")

    def test_apply_environment_does_not_set_secrets(self):
        cfg = AppConfig(glm_api_key="key1", glm_model="model1", glm_base_url="url1")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))
        self.assertFalse(has_secret("GLM_MODEL"))
        self.assertFalse(has_secret("GLM_BASE_URL"))

    def test_apply_environment_no_leak_to_os_environ(self):
        cfg = AppConfig(glm_api_key="secret1")
        cfg.apply_environment()
        self.assertIsNone(os.environ.get("GLM_API_KEY"))

    def test_apply_environment_none_values(self):
        cfg = AppConfig()
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_apply_environment_does_not_overwrite(self):
        set_secret("GLM_API_KEY", "existing")
        cfg = AppConfig(glm_api_key="new")
        cfg.apply_environment()
        self.assertEqual(get_secret("GLM_API_KEY"), "existing")

    def test_apply_environment_masked_value_not_set(self):
        cfg = AppConfig(glm_api_key="********")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_apply_environment_partial_mask_not_set(self):
        cfg = AppConfig(glm_api_key="sk-1****")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))


class TestAppConfigV2(unittest.TestCase):
    def test_parse_bool_true_values(self):
        self.assertTrue(parse_bool_v2(True))
        self.assertTrue(parse_bool_v2("true"))
        self.assertTrue(parse_bool_v2("yes"))
        self.assertTrue(parse_bool_v2("1"))
        self.assertTrue(parse_bool_v2("on"))
        self.assertTrue(parse_bool_v2("ON"))

    def test_parse_bool_false_values(self):
        self.assertFalse(parse_bool_v2(False))
        self.assertFalse(parse_bool_v2("false"))
        self.assertFalse(parse_bool_v2("no"))
        self.assertFalse(parse_bool_v2("0"))
        self.assertFalse(parse_bool_v2("off"))
        self.assertFalse(parse_bool_v2(""))

    def test_parse_bool_none(self):
        self.assertFalse(parse_bool_v2(None))

    def test_parse_bool_int(self):
        self.assertTrue(parse_bool_v2(1))
        self.assertFalse(parse_bool_v2(0))

    def test_validate_config_path_normal(self):
        result = validate_config_path_v2("/some/path", "test")
        self.assertIsInstance(result, Path)

    def test_validate_config_path_empty(self):
        result = validate_config_path_v2("  ", "test")
        self.assertIsNone(result)

    def test_validate_config_path_traversal(self):
        result = validate_config_path_v2("../../etc/passwd", "test")
        self.assertIsNone(result)

    def test_parse_payload_to_app_config(self):
        payload = {
            "interval": 2.0,
            "isolate_mode": True,
            "auto_start": True,
            "glm_api_key": "test-key",
            "glm_model": "glm-4",
            "glm_base_url": "https://api.test.com",
            "ui_language": "en",
            "language_pack": "zh-CN",
        }
        cfg = parse_payload_to_app_config(payload)
        self.assertEqual(cfg.interval, 2.0)
        self.assertTrue(cfg.isolate_mode)
        self.assertTrue(cfg.auto_start)
        self.assertEqual(cfg.glm_api_key, "test-key")

    def test_parse_payload_negative_interval(self):
        cfg = parse_payload_to_app_config({"interval": -1.0})
        self.assertEqual(cfg.interval, 0.8)

    def test_parse_payload_zero_interval(self):
        cfg = parse_payload_to_app_config({"interval": 0})
        self.assertEqual(cfg.interval, 0.8)

    def test_parse_payload_db_path_traversal(self):
        cfg = parse_payload_to_app_config({"db_path": "../../etc/passwd"})
        self.assertIsNone(cfg.db_path)

    def test_parse_payload_empty_db_path(self):
        cfg = parse_payload_to_app_config({"db_path": "  "})
        self.assertIsNone(cfg.db_path)

    def test_load_file_payload_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("interval: 1.5\n", encoding="utf-8")
            payload = load_file_payload(cfg_path)
            self.assertEqual(payload["interval"], 1.5)

    def test_load_file_payload_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.json"
            cfg_path.write_text('{"interval": 2.0}', encoding="utf-8")
            payload = load_file_payload(cfg_path)
            self.assertEqual(payload["interval"], 2.0)

    def test_load_file_payload_malformed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "bad.yaml"
            cfg_path.write_text(":\n  :\n    - invalid: [yaml", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_file_payload(cfg_path)

    def test_load_file_payload_non_dict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "list.yaml"
            cfg_path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_file_payload(cfg_path)

    def test_load_file_payload_null(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "null.yaml"
            cfg_path.write_text("---\n", encoding="utf-8")
            payload = load_file_payload(cfg_path)
            self.assertEqual(payload, {})

    def test_app_config_to_dict(self):
        cfg = AppConfigV2(interval=1.5, isolate_mode=True, glm_api_key="key123")
        d = app_config_to_dict(cfg)
        self.assertEqual(d["interval"], 1.5)
        self.assertTrue(d["isolate_mode"])
        self.assertEqual(d["glm_api_key"], "key123")
        self.assertNotIn("db_path", d)

    def test_app_config_to_dict_with_paths(self):
        cfg = AppConfigV2(db_path=Path("/tmp/test.db"))
        d = app_config_to_dict(cfg)
        self.assertIn("db_path", d)

    def test_candidate_config_paths_with_path(self):
        paths = candidate_config_paths(Path("/custom/config.yaml"))
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0], Path("/custom/config.yaml"))


class TestConfigLoadExtended(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_load_yaml_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text(
                "glm_api_key: yaml-key\nglm_model: glm-test\ninterval: 1.25\n",
                encoding="utf-8",
            )
            cfg = load_config(cfg_path)
            cfg.apply_environment()
            self.assertEqual(cfg.interval, 1.25)
            self.assertFalse(has_secret("GLM_API_KEY"))

    def test_load_json_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.json"
            cfg_path.write_text('{"interval": 2.0, "isolate_mode": true}', encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.interval, 2.0)
            self.assertTrue(cfg.isolate_mode)

    def test_nonexistent_config_returns_default(self):
        cfg = load_config(Path("/nonexistent/config.yaml"))
        self.assertEqual(cfg.interval, 0.8)

    def test_malformed_yaml_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "bad.yaml"
            cfg_path.write_text(":\n  :\n    - [invalid", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(cfg_path)

    def test_non_dict_yaml_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "list.yaml"
            cfg_path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(cfg_path)

    def test_null_yaml_returns_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "null.yaml"
            cfg_path.write_text("---\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_negative_interval_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("interval: -1.0\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_zero_interval_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("interval: 0\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_interval_clamped_to_max(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("interval: 100.0\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_interval_clamped_to_min(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("interval: 0.05\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.interval, 0.1)

    def test_invalid_language_defaults_to_en(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("ui_language: xx-yy\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.ui_language, "en")

    def test_valid_zh_cn_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("ui_language: zh-cn\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.ui_language, "zh-cn")

    def test_db_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("db_path: '../../etc/passwd'\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertIsNone(cfg.db_path)

    def test_empty_db_path_is_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("db_path: '  '\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertIsNone(cfg.db_path)

    def test_language_pack_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("language_pack: zh-CN\n", encoding="utf-8")
            cfg = load_config(cfg_path)
            self.assertEqual(cfg.language_pack, "zh-CN")

    def test_parse_bool_edge_cases(self):
        self.assertTrue(_parse_bool("ON"))
        self.assertTrue(_parse_bool("Yes"))
        self.assertTrue(_parse_bool("1"))
        self.assertFalse(_parse_bool("FALSE"))
        self.assertFalse(_parse_bool("0"))
        self.assertFalse(_parse_bool("No"))
        self.assertFalse(_parse_bool("OFF"))
        self.assertFalse(_parse_bool(""))
        self.assertFalse(_parse_bool(None))
        self.assertFalse(_parse_bool([]))


class TestConfigStoreExtended(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_singleton(self):
        a = ConfigStore.instance()
        b = ConfigStore.instance()
        self.assertIs(a, b)

    def test_reset_creates_new(self):
        a = ConfigStore.instance()
        ConfigStore.reset()
        b = ConfigStore.instance()
        self.assertIsNot(a, b)

    def test_build_full_payload(self):
        store = ConfigStore.instance()
        payload = store.build_full_payload()
        self.assertIsInstance(payload, dict)
        self.assertIn("interval", payload)

    def test_build_disk_yaml_text(self):
        store = ConfigStore.instance()
        text = store.build_disk_yaml_text()
        self.assertIsInstance(text, str)

    def test_request_update_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 2.0})
            self.assertEqual(store.config.interval, 2.0)

    def test_request_update_string_interval_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original = store.config.interval
            store.request_update_and_save({"interval": "fast"})
            self.assertEqual(store.config.interval, original)

    def test_request_update_small_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 0.001})
            self.assertEqual(store.config.interval, 0.1)

    def test_request_update_negative_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": -5.0})
            self.assertEqual(store.config.interval, 0.1)

    def test_request_update_large_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 100.0})
            self.assertEqual(store.config.interval, 60.0)

    def test_request_update_auto_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"auto_start": True})
            self.assertTrue(store.config.auto_start)

    def test_request_update_isolate_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"isolate_mode": True})
            self.assertTrue(store.config.isolate_mode)

    def test_request_update_glm_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"glm_api_key": "new-key"})
            self.assertEqual(store.config.glm_api_key, "new-key")

    def test_request_update_glm_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"glm_model": "glm-4v"})
            self.assertEqual(store.config.glm_model, "glm-4v")

    def test_request_update_glm_base_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"glm_base_url": "https://api.new.com"})
            self.assertEqual(store.config.glm_base_url, "https://api.new.com")

    def test_request_update_invalid_language_keeps_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original = store.config.ui_language
            store.request_update_and_save({"ui_language": "invalid"})
            self.assertEqual(store.config.ui_language, original)

    def test_concurrent_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            errors = []

            def updater(idx):
                try:
                    store.request_update_and_save({"interval": float(idx)})
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=updater, args=(i,)) for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            self.assertEqual(len(errors), 0)

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 3.0, "auto_start": True})
            saved_path = config_file_path()
            self.assertTrue(saved_path.exists())
            reloaded = load_config(saved_path)
            self.assertEqual(reloaded.interval, 3.0)
            self.assertTrue(reloaded.auto_start)


class TestHistoryStoreExtended(unittest.TestCase):
    def _make_event(self, hash_prefix="test", idx=0, status="ok", error=None):
        return ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash=f"{hash_prefix}_{idx}",
            image_width=100,
            image_height=100,
            latex=f"x^{idx}",
            source="test",
            status=status,
            error=error,
        )

    def test_add_and_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                latest = store.latest()
                self.assertIsNotNone(latest)
                self.assertEqual(latest.image_hash, "test_0")

    def test_latest_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                self.assertIsNone(store.latest())

    def test_add_multiple_and_list_recent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(5):
                    store.add(self._make_event(idx=i))
                recent = store.list_recent(limit=3)
                self.assertEqual(len(recent), 3)

    def test_list_recent_invalid_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                self.assertIsInstance(store.list_recent(limit=-1), list)
                self.assertIsInstance(store.list_recent(limit=0), list)
                self.assertIsInstance(store.list_recent(limit="invalid"), list)

    def test_error_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event(status="error", error="Something went wrong"))
                latest = store.latest()
                self.assertEqual(latest.status, "error")
                self.assertEqual(latest.error, "Something went wrong")

    def test_double_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            store.close()

    def test_add_after_close_does_nothing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            store.add(self._make_event())

    def test_list_recent_after_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            self.assertEqual(store.list_recent(), [])

    def test_truncate_field(self):
        self.assertEqual(_truncate_field("short", "image_hash"), "short")
        long_val = "x" * 200
        truncated = _truncate_field(long_val, "image_hash")
        self.assertLessEqual(len(truncated), 128)
        self.assertTrue(truncated.endswith("..."))

    def test_truncate_field_unknown_name(self):
        val = "x" * 200
        result = _truncate_field(val, "unknown_field")
        self.assertEqual(result, val)

    def test_very_long_field_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                event = ClipboardEvent(
                    created_at=datetime.now(timezone.utc),
                    image_hash="h" * 200,
                    image_width=100,
                    image_height=100,
                    latex="x" * 100000,
                    source="s" * 600,
                    status="ok",
                )
                store.add(event)
                latest = store.latest()
                self.assertLessEqual(len(latest.latex), 65536)
                self.assertLessEqual(len(latest.image_hash), 128)

    def test_concurrent_writes(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            errors = []

            def writer(idx):
                try:
                    for i in range(10):
                        store.add(self._make_event(hash_prefix=f"w{idx}", idx=i))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
            self.assertEqual(len(errors), 0)
            store.close()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            HistoryStore(Path("../../etc/history.sqlite3"))

    def test_corrupted_database_recovery(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test.sqlite3"
            db_path.write_bytes(b"not a valid sqlite database content")
            try:
                store = HistoryStore(db_path)
                store.close()
            except Exception:
                pass
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_connection_recovery(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            if store._connection is not None:
                try:
                    store._connection.close()
                except Exception:
                    pass
                store._connection = None
            store.add(self._make_event())
            latest = store.latest()
            self.assertIsNotNone(latest)
            store.close()

    def test_auto_vacuum_under_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(10):
                    store.add(self._make_event(idx=i))
                count = store._connection.execute("SELECT COUNT(*) FROM clipboard_history").fetchone()[0]
                self.assertLessEqual(count, _MAX_HISTORY_ROWS)

    def test_context_manager(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                self.assertIsNotNone(store.latest())

    def test_ensure_utc_naive_datetime(self):
        dt = datetime(2024, 1, 1, 12, 0, 0)
        result = HistoryStore._ensure_utc(dt)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_ensure_utc_aware_datetime(self):
        dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = HistoryStore._ensure_utc(dt)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_default_db_path(self):
        store = HistoryStore()
        self.assertIsNotNone(store.db_path)
        self.assertTrue(str(store.db_path).endswith("history.sqlite3"))
        store.close()


class TestEventBusExtended(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_emit_no_subscribers(self):
        bus = EventBus()
        bus.emit(OcrSuccessEvent(latex="test"))

    def test_subscribe_and_emit(self):
        bus = EventBus()
        received = []
        bus.subscribe(OcrSuccessEvent, lambda e: received.append(e))
        bus.emit(OcrSuccessEvent(latex="x^2"))
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].latex, "x^2")

    def test_subscriber_exception_does_not_break_others(self):
        bus = EventBus()
        bad_called = threading.Event()
        good_called = threading.Event()

        def bad_cb(e):
            bad_called.set()
            raise RuntimeError("fail")

        def good_cb(e):
            good_called.set()

        bus.subscribe(OcrSuccessEvent, bad_cb)
        bus.subscribe(OcrSuccessEvent, good_cb)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertTrue(bad_called.wait(timeout=2))
        self.assertTrue(good_called.wait(timeout=2))

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        cb = lambda e: received.append(e)
        bus.subscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="1"))
        bus.unsubscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="2"))
        self.assertEqual(len(received), 1)

    def test_unsubscribe_all(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.unsubscribe_all()
        self.assertEqual(len(bus._subscribers.get(OcrSuccessEvent, [])), 0)

    def test_unsubscribe_specific_type(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(AppStateChangedEvent, lambda e: None)
        bus.unsubscribe_all(OcrSuccessEvent)
        self.assertIsNone(bus._subscribers.get(OcrSuccessEvent))
        self.assertIn(AppStateChangedEvent, bus._subscribers)

    def test_clear(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.clear()
        bus.emit(OcrSuccessEvent())

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

        threads = [threading.Thread(target=subscriber), threading.Thread(target=emitter)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_subscriber_count(self):
        bus = EventBus()
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 0)
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 1)
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(OcrSuccessEvent), 2)

    def test_subscriber_count_total(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(AppStateChangedEvent, lambda e: None)
        self.assertEqual(bus.subscriber_count(), 2)

    def test_multiple_event_types(self):
        bus = EventBus()
        ocr_received = []
        state_received = []
        bus.subscribe(OcrSuccessEvent, lambda e: ocr_received.append(e))
        bus.subscribe(AppStateChangedEvent, lambda e: state_received.append(e))
        bus.emit(OcrSuccessEvent(latex="x"))
        bus.emit(AppStateChangedEvent(old_state="IDLE", new_state="RUNNING"))
        self.assertEqual(len(ocr_received), 1)
        self.assertEqual(len(state_received), 1)

    def test_all_event_types_are_frozen(self):
        event_types = [
            OcrSuccessEvent, OcrErrorEvent, AppStateChangedEvent,
            ConfigChangedEvent, HotkeyStatusChangedEvent,
            ClipboardPublishingEvent, ShowPanelEvent, ShutdownRequestEvent,
        ]
        for evt_type in event_types:
            event = evt_type()
            with self.assertRaises((AttributeError, TypeError)):
                event.new_attr = "should fail"

    def test_unsubscribe_during_emit(self):
        bus = EventBus()
        called = threading.Event()

        def cb(event):
            called.set()
            bus.unsubscribe(OcrSuccessEvent, cb)

        bus.subscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertTrue(called.wait(timeout=2))


class TestStateMachineExtended(unittest.TestCase):
    def test_initial_state_is_idle(self):
        sm = StateMachine()
        self.assertEqual(sm.state, AppState.IDLE)

    def test_valid_transition(self):
        sm = StateMachine()
        self.assertTrue(sm.transition_to(AppState.STARTING))
        self.assertEqual(sm.state, AppState.STARTING)

    def test_invalid_transition(self):
        sm = StateMachine()
        self.assertFalse(sm.transition_to(AppState.RUNNING))
        self.assertEqual(sm.state, AppState.IDLE)

    def test_full_lifecycle(self):
        sm = StateMachine()
        self.assertTrue(sm.transition_to(AppState.STARTING))
        self.assertTrue(sm.transition_to(AppState.RUNNING))
        self.assertTrue(sm.transition_to(AppState.STOPPING))
        self.assertTrue(sm.transition_to(AppState.STOPPED))
        self.assertTrue(sm.transition_to(AppState.IDLE))

    def test_force_state(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertEqual(sm.state, AppState.RUNNING)

    def test_can_transition_to(self):
        sm = StateMachine()
        self.assertTrue(sm.can_transition_to(AppState.STARTING))
        self.assertFalse(sm.can_transition_to(AppState.RUNNING))

    def test_is_running(self):
        sm = StateMachine()
        self.assertFalse(sm.is_running)
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.is_running)

    def test_is_stopped(self):
        sm = StateMachine()
        self.assertTrue(sm.is_stopped)
        sm.force_state(AppState.RUNNING)
        self.assertFalse(sm.is_stopped)
        sm.force_state(AppState.STOPPED)
        self.assertTrue(sm.is_stopped)

    def test_transition_callback(self):
        sm = StateMachine()
        transitions = []
        sm.on_transition(lambda old, new: transitions.append((old, new)))
        sm.transition_to(AppState.STARTING)
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0], (AppState.IDLE, AppState.STARTING))

    def test_callback_exception_does_not_break(self):
        sm = StateMachine()
        bad_called = threading.Event()
        good_called = threading.Event()

        def bad_cb(old, new):
            bad_called.set()
            raise RuntimeError("fail")

        def good_cb(old, new):
            good_called.set()

        sm.on_transition(bad_cb)
        sm.on_transition(good_cb)
        result = sm.transition_to(AppState.STARTING)
        self.assertTrue(result)
        self.assertTrue(bad_called.wait(timeout=2))
        self.assertTrue(good_called.wait(timeout=2))

    def test_concurrent_transitions(self):
        sm = StateMachine()
        errors = []

        def transition_loop():
            try:
                for _ in range(50):
                    sm.transition_to(AppState.STARTING)
                    sm.transition_to(AppState.RUNNING)
                    sm.transition_to(AppState.STOPPING)
                    sm.transition_to(AppState.STOPPED)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=transition_loop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(errors), 0)

    def test_paused_state(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.transition_to(AppState.PAUSED))
        self.assertEqual(sm.state, AppState.PAUSED)
        self.assertTrue(sm.transition_to(AppState.RUNNING))

    def test_stopped_to_starting(self):
        sm = StateMachine()
        sm.force_state(AppState.STOPPED)
        self.assertTrue(sm.transition_to(AppState.STARTING))


class TestPopupManagerExtended(unittest.TestCase):
    def test_show_popup(self):
        pm = PopupManager()
        pm.show_popup("Title", "Content", 5000)
        self.assertFalse(pm.popup_queue.empty())

    def test_show_popup_when_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.show_popup("Title", "Content")
        self.assertTrue(pm.popup_queue.empty() or pm.popup_queue.get_nowait() is None)

    def test_open_panel(self):
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

    def test_confirm_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        self.assertFalse(pm._shutdown_confirmed.is_set())
        pm.confirm_shutdown()
        self.assertTrue(pm._shutdown_confirmed.is_set())

    def test_wait_for_shutdown_timeout(self):
        pm = PopupManager()
        self.assertFalse(pm.wait_for_shutdown(timeout=0.1))

    def test_wait_for_shutdown_confirmed(self):
        pm = PopupManager()
        pm.confirm_shutdown()
        self.assertTrue(pm.wait_for_shutdown(timeout=1.0))

    def test_queue_overflow(self):
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
        self.assertGreater(pm._bus.subscriber_count(OcrSuccessEvent), 0)
        pm.unsubscribe_ocr_events()

    def test_on_ocr_success(self):
        pm = PopupManager()
        pm._on_ocr_success(OcrSuccessEvent(latex="x^2"))
        self.assertFalse(pm.popup_queue.empty())


class TestApiKeyMaskingExtended(unittest.TestCase):
    def test_is_sensitive_key(self):
        self.assertTrue(is_sensitive_key("api_key"))
        self.assertTrue(is_sensitive_key("glm_api_key"))
        self.assertTrue(is_sensitive_key("secret"))
        self.assertTrue(is_sensitive_key("my_token"))
        self.assertTrue(is_sensitive_key("password"))
        self.assertTrue(is_sensitive_key("apikey"))
        self.assertFalse(is_sensitive_key("name"))
        self.assertFalse(is_sensitive_key("enabled"))
        self.assertFalse(is_sensitive_key("api"))

    def test_strip_api_keys_basic(self):
        data = {"api_key": "sk-1234567890abcdef"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_strip_api_keys_short(self):
        data = {"api_key": "abc"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_strip_api_keys_empty(self):
        data = {"api_key": ""}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "")

    def test_strip_api_keys_non_string(self):
        data = {"api_key": 12345}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], 12345)

    def test_strip_api_keys_nested(self):
        data = {"scripts": {"my_script": {"api_key": "sk-1234567890"}}}
        result = strip_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "********")

    def test_strip_api_keys_list(self):
        data = {"items": [{"api_key": "secret123"}, {"name": "test"}]}
        result = strip_api_keys(data)
        self.assertEqual(result["items"][0]["api_key"], "********")
        self.assertEqual(result["items"][1]["name"], "test")

    def test_strip_does_not_modify_original(self):
        data = {"api_key": "secret123"}
        result = strip_api_keys(data)
        self.assertEqual(data["api_key"], "secret123")
        self.assertNotEqual(result["api_key"], "secret123")

    def test_is_masked_value(self):
        self.assertTrue(_is_masked_value("********"))
        self.assertTrue(_is_masked_value("***"))
        self.assertTrue(_is_masked_value("sk-1****"))
        self.assertTrue(_is_masked_value("****"))
        self.assertFalse(_is_masked_value("real-key"))
        self.assertFalse(_is_masked_value("sk-12345"))

    def test_hide_api_key(self):
        text = "glm_api_key: sk-real-key-12345\n"
        result = hide_api_key(text)
        self.assertNotIn("sk-real-key-12345", result)
        self.assertIn("***", result)

    def test_hide_api_key_multiple(self):
        text = "api_key: key1\ntoken: key2\nname: plain\n"
        result = hide_api_key(text)
        self.assertNotIn("key1", result)
        self.assertNotIn("key2", result)
        self.assertIn("plain", result)

    def test_restore_api_key_masked(self):
        edited = "glm_api_key: ***\n"
        original = "glm_api_key: sk-real-key-12345\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real-key-12345", result)

    def test_restore_api_key_non_masked(self):
        edited = "glm_api_key: new-key\n"
        original = "glm_api_key: old-key\n"
        result = restore_api_key(edited, original)
        self.assertIn("new-key", result)

    def test_restore_api_key_trailing_newline(self):
        edited = "glm_api_key: ***\n"
        original = "glm_api_key: sk-real-key\n"
        result = restore_api_key(edited, original)
        self.assertTrue(result.endswith("\n"))

    def test_restore_api_key_partial_mask(self):
        edited = "glm_api_key: sk-1****\n"
        original = "glm_api_key: sk-1234567890\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-1234567890", result)

    def test_fill_masked_api_keys(self):
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "********")

    def test_fill_non_masked_keeps_value(self):
        data = {"glm_api_key": "actual-key"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "actual-key")

    def test_fill_masked_no_secret_keeps_masked(self):
        clear_all()
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "********")

    def test_fill_masked_scripts(self):
        data = {"scripts": {"my_script": {"api_key": "actual-key"}}}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "actual-key")


class TestScriptSafetyExtended(unittest.TestCase):
    def test_validate_empty_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty.py"
            path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(path)

    def test_validate_oversized_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "big.py"
            path.write_text("x = 1\n" * 200000, encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(path)

    def test_validate_nonexistent_script(self):
        with self.assertRaises(FileNotFoundError):
            validate_script_path(Path("/nonexistent/script.py"))

    def test_validate_path_traversal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".." / ".." / "etc" / "passwd"
            with self.assertRaises((ValueError, FileNotFoundError)):
                validate_script_path(path)

    def test_load_script_syntax_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.py"
            path.write_text("def broken(\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _load_script_module(path)

    def test_load_script_runtime_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "runtime_err.py"
            path.write_text("raise RuntimeError('init error')\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _load_script_module(path)

    def test_safe_script_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "safe.py"
            path.write_text("def process_image(image_bytes, context):\n    return 'ok'\n", encoding="utf-8")
            _check_dangerous_patterns(path)

    def test_os_system_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dangerous.py"
            path.write_text("import os\nos.system('echo pwned')\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(path)

    def test_exec_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "evil.py"
            path.write_text("exec('print(1)')\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(path)

    def test_eval_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "evil.py"
            path.write_text("eval('1+1')\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(path)

    def test_subprocess_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "evil.py"
            path.write_text("import subprocess\nsubprocess.run(['ls'])\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(path)

    def test_scan_script_source_returns_warnings_and_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dangerous.py"
            path.write_text("import os\nos.system('echo pwned')\n", encoding="utf-8")
            warnings, blocked = scan_script_source(path)
            self.assertTrue(len(blocked) > 0)

    def test_check_blocked_patterns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "evil.py"
            path.write_text("exec('print(1)')\n", encoding="utf-8")
            blocked = check_blocked_patterns(path)
            self.assertIn("exec()", blocked)

    def test_extract_legacy_result_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 'x^2'\n", encoding="utf-8")
            module = _load_script_module(path)
            result = _extract_legacy_result(module, path, "x^2")
            self.assertEqual(result, "x^2")

    def test_extract_legacy_result_dict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return {'latex': 'x^2'}\n", encoding="utf-8")
            module = _load_script_module(path)
            result = _extract_legacy_result(module, path, {"latex": "x^2"})
            self.assertEqual(result, "x^2")

    def test_extract_legacy_result_unsupported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 42\n", encoding="utf-8")
            module = _load_script_module(path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, path, 42)

    def test_extract_legacy_result_empty_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return '  '\n", encoding="utf-8")
            module = _load_script_module(path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, path, "  ")

    def test_dangerous_patterns_with_env_override(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dangerous.py"
            path.write_text("import socket\n\ndef process_image(b, c): return 'x'\n", encoding="utf-8")
            old_val = os.environ.get("PLATEX_ALLOW_UNSAFE_SCRIPTS")
            try:
                os.environ["PLATEX_ALLOW_UNSAFE_SCRIPTS"] = "1"
                _check_dangerous_patterns(path)
            finally:
                if old_val is None:
                    os.environ.pop("PLATEX_ALLOW_UNSAFE_SCRIPTS", None)
                else:
                    os.environ["PLATEX_ALLOW_UNSAFE_SCRIPTS"] = old_val

    def test_scan_nonexistent_file(self):
        warnings, blocked = scan_script_source(Path("/nonexistent/file.py"))
        self.assertEqual(warnings, [])
        self.assertEqual(blocked, [])


class TestScriptRegistryExtended(unittest.TestCase):
    def test_load_nonexistent(self):
        registry = ScriptRegistry()
        result = registry.load_script_file(Path("/nonexistent/script.py"))
        self.assertIsNone(result)

    def test_discover_nonexistent_dir(self):
        registry = ScriptRegistry()
        registry.discover_scripts(Path("/nonexistent/scripts"))

    def test_load_no_interface(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "noop.py"
            path.write_text("x = 42\n", encoding="utf-8")
            registry = ScriptRegistry()
            result = registry._load_script_file(path)
            self.assertIsNone(result)

    def test_load_and_get_ocr_scripts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ocr.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            ocr = registry.get_ocr_scripts()
            self.assertGreaterEqual(len(ocr), 1)

    def test_get_hotkey_scripts_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "no_hotkey.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            self.assertEqual(len(registry.get_hotkey_scripts()), 0)

    def test_get_enabled_scripts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            self.assertGreaterEqual(len(registry.get_enabled_scripts()), 1)

    def test_get_all_scripts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            self.assertGreaterEqual(len(registry.get_all_scripts()), 1)

    def test_clear(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            registry.clear()
            self.assertEqual(len(registry.entries), 0)

    def test_get_entry(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "myscript.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            entry = registry.get("myscript")
            self.assertIsNotNone(entry)

    def test_get_nonexistent_entry(self):
        registry = ScriptRegistry()
        self.assertIsNone(registry.get("nonexistent"))

    def test_load_configs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            registry.load_configs({"script": {"enabled": False}})
            entry = registry.get("script")
            self.assertFalse(entry.enabled)

    def test_load_configs_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            registry.load_configs({"script": "not_a_dict"})

    def test_save_configs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(path)
            configs = registry.save_configs()
            self.assertIn("script", configs)
            self.assertIn("enabled", configs["script"])

    def test_duplicate_script_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ScriptRegistry()
            script1 = Path(temp_dir) / "myscript.py"
            script1.write_text("def process_image(b, c): return 's1'\n", encoding="utf-8")
            script2 = Path(temp_dir) / "subdir" / "myscript.py"
            script2.parent.mkdir(parents=True, exist_ok=True)
            script2.write_text("def process_image(b, c): return 's2'\n", encoding="utf-8")
            registry._load_script_file(script1)
            registry._load_script_file(script2)
            self.assertEqual(len(registry.entries), 1)

    def test_load_script_file_with_dangerous_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "dangerous.py"
            path.write_text("import os\nos.system('echo pwned')\ndef process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            with self.assertRaises(ValueError):
                registry._load_script_file(path)

    def test_load_script_file_enabled_param(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            registry = ScriptRegistry()
            entry = registry.load_script_file(path, enabled=False)
            self.assertFalse(entry.enabled)

    def test_discover_scripts_from_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = Path(temp_dir) / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "script1.py").write_text("def process_image(b, c): return 'x'\n", encoding="utf-8")
            (scripts_dir / "_private.py").write_text("def process_image(b, c): return 'y'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry.discover_scripts(scripts_dir)
            self.assertIn("script1", registry.entries)
            self.assertNotIn("_private", registry.entries)


class TestLoaderExtended(unittest.TestCase):
    def test_load_script_processor_string_return(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return r'\\alpha'\n", encoding="utf-8")
            proc = load_script_processor(path)
            result = proc.process_image(b"test", {})
            self.assertEqual(result, r"\alpha")

    def test_load_script_processor_dict_return(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return {'latex': 'x^2'}\n", encoding="utf-8")
            proc = load_script_processor(path)
            result = proc.process_image(b"test", {})
            self.assertEqual(result, "x^2")

    def test_load_script_processor_unsupported_return(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return 42\n", encoding="utf-8")
            proc = load_script_processor(path)
            with self.assertRaises(RuntimeError):
                proc.process_image(b"test", {})

    def test_load_script_processor_empty_return(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.py"
            path.write_text("def process_image(b, c): return '  '\n", encoding="utf-8")
            proc = load_script_processor(path)
            with self.assertRaises(RuntimeError):
                proc.process_image(b"test", {})

    def test_load_script_no_entry_point(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "noop.py"
            path.write_text("x = 42\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_script_processor(path)

    def test_load_script_with_create_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "newstyle.py"
            path.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    @property\n    def name(self): return 'my'\n"
                "    @property\n    def display_name(self): return 'My'\n"
                "    @property\n    def description(self): return 'Test'\n"
                "    def has_ocr_capability(self): return True\n"
                "    def process_image(self, b, c=None): return 'x^2'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            proc = load_script_processor(path)
            self.assertIsInstance(proc, OcrProcessorAdapter)
            result = proc.process_image(b"test", {})
            self.assertEqual(result, "x^2")

    def test_load_script_processor_returns_legacy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy.py"
            path.write_text("def process_image(b, c): return r'\\beta'\n", encoding="utf-8")
            proc = load_script_processor(path)
            self.assertIsInstance(proc, LegacyProcessor)


class TestI18nExtended(unittest.TestCase):
    def test_initialize_en(self):
        initialize("en")
        self.assertEqual(get_current_language(), "en")

    def test_initialize_invalid_falls_back_to_en(self):
        initialize("nonexistent")
        self.assertEqual(get_current_language(), "en")

    def test_t_returns_key_for_missing(self):
        initialize("en")
        result = t("nonexistent.key.12345")
        self.assertEqual(result, "nonexistent.key.12345")

    def test_t_with_kwargs(self):
        initialize("en")
        result = t("nonexistent.{name}", name="test")
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

    def test_switch_language_same_noop(self):
        initialize("en")
        switch_language("en")
        self.assertEqual(get_current_language(), "en")

    def test_switch_language_invalid_keeps_current(self):
        initialize("en")
        switch_language("nonexistent")
        self.assertEqual(get_current_language(), "en")

    def test_on_language_changed(self):
        initialize("en")
        changes = []
        on_language_changed(lambda lang: changes.append(lang))
        switch_language("zh-cn")
        self.assertIn("zh-cn", changes)
        remove_language_callback(changes.append)

    def test_remove_language_callback(self):
        initialize("en")
        changes = []
        cb = lambda lang: changes.append(lang)
        on_language_changed(cb)
        remove_language_callback(cb)
        switch_language("zh-cn")
        switch_language("en")


class TestConfigManagerExtended(unittest.TestCase):
    def test_deep_merge(self):
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 99}, "e": 5}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"]["c"], 99)
        self.assertEqual(result["b"]["d"], 3)
        self.assertEqual(result["e"], 5)

    def test_deep_merge_does_not_modify_original(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        result = deep_merge(base, override)
        self.assertNotIn("y", base["a"])

    def test_deep_merge_empty_base(self):
        result = deep_merge({}, {"a": 1})
        self.assertEqual(result["a"], 1)

    def test_deep_merge_empty_override(self):
        result = deep_merge({"a": 1}, {})
        self.assertEqual(result["a"], 1)

    def test_deep_merge_override_non_dict(self):
        result = deep_merge({"a": {"x": 1}}, {"a": "string"})
        self.assertEqual(result["a"], "string")

    def test_apply_migrations_v1_to_v2(self):
        payload = {"interval": 1.0}
        result = _apply_migrations(payload, 1, 2)
        self.assertIn("ui_language", result)
        self.assertIn("scripts", result)
        self.assertIn("glm_vision_ocr", result["scripts"])
        self.assertIn("hotkey_click", result["scripts"])

    def test_apply_migrations_already_v2(self):
        payload = {"interval": 1.0, "ui_language": "zh-cn"}
        result = _apply_migrations(payload, 2, 2)
        self.assertEqual(result, payload)

    def test_import_nonexistent_file(self):
        cm = ConfigManager()
        with self.assertRaises(FileNotFoundError):
            cm.import_all(Path("/nonexistent/config.yaml"))

    def test_import_oversized_file(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            big = Path(temp_dir) / "big.yaml"
            big.write_bytes(b"x: " + b"a" * (2 * 1024 * 1024))
            with self.assertRaises(ValueError):
                cm.import_all(big)

    def test_import_non_dict_yaml(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "list.yaml"
            path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cm.import_all(path)

    def test_import_empty_yaml(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "empty.yaml"
            path.write_text("---\n", encoding="utf-8")
            result = cm.import_all(path)
            self.assertEqual(result, {})

    def test_import_filters_unknown_keys(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "extra.yaml"
            path.write_text("general:\n  interval: 1.5\n  dangerous_key: hack\n", encoding="utf-8")
            result = cm.import_all(path)
            self.assertIn("general", result)
            self.assertNotIn("dangerous_key", result["general"])

    def test_import_script_nonexistent(self):
        cm = ConfigManager()
        with self.assertRaises(FileNotFoundError):
            cm.import_script(Path("/nonexistent/script.yaml"))

    def test_export_script_no_registry(self):
        cm = ConfigManager()
        with self.assertRaises(RuntimeError):
            cm.export_script("test", Path("/tmp/test.yaml"))

    def test_export_script_not_found(self):
        registry = MagicMock()
        registry.get.return_value = None
        cm = ConfigManager(registry)
        with self.assertRaises(ValueError):
            cm.export_script("nonexistent", Path("/tmp/test.yaml"))

    def test_import_script_invalid_name(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.yaml"
            path.write_text("__script_name__: '123invalid'\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cm.import_script(path)

    def test_import_script_empty_file(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.yaml"
            path.write_text("---\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cm.import_script(path)

    def test_import_script_non_dict(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "script.yaml"
            path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cm.import_script(path)

    def test_import_script_oversized(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "big.yaml"
            path.write_bytes(b"x: " + b"a" * (2 * 1024 * 1024))
            with self.assertRaises(ValueError):
                cm.import_script(path)

    def test_export_all(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            cm = ConfigManager()
            export_path = Path(temp_dir) / "export.yaml"
            cm.export_all(export_path)
            self.assertTrue(export_path.exists())

    def test_backup_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            cfg_path = Path(temp_dir) / "config.yaml"
            cfg_path.write_text("interval: 1.0\n", encoding="utf-8")
            result = backup_config()
            self.assertIsNotNone(result)

    def test_backup_config_no_existing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            set_config_dir(Path(temp_dir))
            result = backup_config()
            self.assertIsNone(result)


class TestClipboardWatcherExtended(unittest.TestCase):
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
        return ClipboardWatcher(processor=processor, history=history, source_name="test")

    def test_poll_no_image(self):
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

    def test_ocr_timeout(self):
        class HangingProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                time.sleep(10)
                return "never"

        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=HangingProcessor(), history=history,
            source_name="test", ocr_timeout=0.5,
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("timed out", result.error)
        watcher.close()

    def test_ocr_exception(self):
        class FailingProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                raise RuntimeError("OCR failure")

        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=FailingProcessor(), history=history, source_name="test",
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("OCR failure", result.error)
        watcher.close()

    def test_history_write_failure(self):
        class FailingHistory:
            def add(self, event):
                raise sqlite3.OperationalError("locked")
            def close(self):
                pass

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(), history=FailingHistory(), source_name="test",
        )
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        watcher.close()

    def test_close_safe_when_history_none(self):
        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(), history=history, source_name="test",
        )
        watcher.history = None
        watcher.close()
        history.close()

    def test_cleanup_orphan_threads(self):
        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(), history=history, source_name="test",
        )
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()
        watcher._orphan_threads.append(dead_thread)
        watcher._cleanup_orphan_threads()
        self.assertEqual(len(watcher._orphan_threads), 0)
        watcher.close()

    def test_duplicate_image_hash_skipped(self):
        watcher = self._make_watcher()
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result1 = watcher.poll_once()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result2 = watcher.poll_once()
        self.assertIsNotNone(result1)
        self.assertIsNone(result2)
        watcher.close()

    def test_force_poll_ignores_hash(self):
        watcher = self._make_watcher()
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result1 = watcher.poll_once()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result2 = watcher.poll_once(force=True)
        self.assertIsNotNone(result1)
        self.assertIsNotNone(result2)
        watcher.close()


class TestConvertHotkeyStrExtended(unittest.TestCase):
    def test_ctrl_alt_1(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Alt+1"), "<ctrl>+<alt>+1")

    def test_ctrl_shift_f5(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Shift+F5"), "<ctrl>+<shift>+<f5>")

    def test_win_key(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Win+K"), "<cmd>+k")

    def test_empty_raises(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        with self.assertRaises(ValueError):
            convert_hotkey_str("")

    def test_whitespace_raises(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        with self.assertRaises(ValueError):
            convert_hotkey_str("   ")

    def test_comma_separated_takes_first(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Alt+1, Ctrl+Alt+2"), "<ctrl>+<alt>+1")

    def test_space_key(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Space"), "<ctrl>+<space>")

    def test_enter_key(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Enter"), "<ctrl>+<enter>")

    def test_plus_only_raises(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        with self.assertRaises(ValueError):
            convert_hotkey_str("+")

    def test_trailing_plus_raises(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        with self.assertRaises(ValueError):
            convert_hotkey_str("Ctrl+")

    def test_tab_key(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Tab"), "<ctrl>+<tab>")

    def test_escape_key(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Esc"), "<escape>")

    def test_delete_key(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Delete"), "<ctrl>+<delete>")

    def test_f12_key(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("F12"), "<f12>")

    def test_single_letter(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("A"), "a")

    def test_alt_shift_s(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Alt+Shift+S"), "<alt>+<shift>+s")

    def test_ctrl_cmd_mixed(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Super+L"), "<ctrl>+<cmd>+l")

    def test_page_up(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Page Up"), "<ctrl>+<page_up>")

    def test_caps_lock(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("CapsLock"), "<caps_lock>")


class TestWin32HotkeyParseExtended(unittest.TestCase):
    def _get_listener(self):
        from platex_client.win32_hotkey import Win32HotkeyListener
        return Win32HotkeyListener()

    def test_parse_ctrl_alt_1(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("<ctrl>+<alt>+1")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0002)
        self.assertTrue(modifiers & 0x0001)
        self.assertEqual(vk, 0x31)

    def test_parse_empty_string(self):
        listener = self._get_listener()
        self.assertIsNone(listener._parse_hotkey(""))

    def test_parse_single_key(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertEqual(modifiers, 0)
        self.assertEqual(vk, 0x41)

    def test_parse_unknown_key(self):
        listener = self._get_listener()
        self.assertIsNone(listener._parse_hotkey("unknownkey"))

    def test_parse_ctrl_only_returns_none(self):
        listener = self._get_listener()
        self.assertIsNone(listener._parse_hotkey("<ctrl>"))

    def test_parse_win_modifier(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("<cmd>+k")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0008)

    def test_parse_numpad_keys(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("<numpad0>")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x60)

    def test_parse_semicolon(self):
        listener = self._get_listener()
        result = listener._parse_hotkey(";")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0xBA)

    def test_parse_f12(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("<f12>")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x7B)

    def test_parse_space(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("<space>")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x20)

    def test_parse_enter(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("<enter>")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x0D)

    def test_parse_shift_modifier(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("<shift>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0004)
        self.assertEqual(vk, 0x41)

    def test_parse_all_modifiers(self):
        listener = self._get_listener()
        result = listener._parse_hotkey("<ctrl>+<alt>+<shift>+<cmd>+a")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0002)
        self.assertTrue(modifiers & 0x0001)
        self.assertTrue(modifiers & 0x0004)
        self.assertTrue(modifiers & 0x0008)

    def test_get_status(self):
        listener = self._get_listener()
        status = listener.get_status()
        self.assertIn("registered", status)
        self.assertIn("failed", status)
        self.assertIn("running", status)

    def test_clear(self):
        listener = self._get_listener()
        listener.clear()
        status = listener.get_status()
        self.assertEqual(len(status["registered"]), 0)


class TestHotkeyRoundtripExtended(unittest.TestCase):
    def test_roundtrip_ctrl_alt_1(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        from platex_client.win32_hotkey import Win32HotkeyListener
        listener = Win32HotkeyListener()
        pynput_key = convert_hotkey_str("Ctrl+Alt+1")
        self.assertIsNotNone(listener._parse_hotkey(pynput_key))

    def test_roundtrip_ctrl_shift_f12(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        from platex_client.win32_hotkey import Win32HotkeyListener
        listener = Win32HotkeyListener()
        pynput_key = convert_hotkey_str("Ctrl+Shift+F12")
        self.assertIsNotNone(listener._parse_hotkey(pynput_key))

    def test_roundtrip_ctrl_space(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        from platex_client.win32_hotkey import Win32HotkeyListener
        listener = Win32HotkeyListener()
        pynput_key = convert_hotkey_str("Ctrl+Space")
        self.assertIsNotNone(listener._parse_hotkey(pynput_key))

    def test_roundtrip_alt_shift_s(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        from platex_client.win32_hotkey import Win32HotkeyListener
        listener = Win32HotkeyListener()
        pynput_key = convert_hotkey_str("Alt+Shift+S")
        self.assertIsNotNone(listener._parse_hotkey(pynput_key))

    def test_roundtrip_win_k(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        from platex_client.win32_hotkey import Win32HotkeyListener
        listener = Win32HotkeyListener()
        pynput_key = convert_hotkey_str("Win+K")
        self.assertIsNotNone(listener._parse_hotkey(pynput_key))

    def test_roundtrip_ctrl_enter(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        from platex_client.win32_hotkey import Win32HotkeyListener
        listener = Win32HotkeyListener()
        pynput_key = convert_hotkey_str("Ctrl+Enter")
        self.assertIsNotNone(listener._parse_hotkey(pynput_key))


class TestLoggingUtils(unittest.TestCase):
    def test_sensitive_data_filter_masks_api_key(self):
        from platex_client.logging_utils import _SensitiveDataFilter
        filt = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "api_key=secret123", (), None)
        filt.filter(record)
        self.assertNotIn("secret123", record.msg)
        self.assertIn("***", record.msg)

    def test_sensitive_data_filter_masks_token(self):
        from platex_client.logging_utils import _SensitiveDataFilter
        filt = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "token=abc123", (), None)
        filt.filter(record)
        self.assertNotIn("abc123", record.msg)

    def test_sensitive_data_filter_masks_password(self):
        from platex_client.logging_utils import _SensitiveDataFilter
        filt = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "password=mypass", (), None)
        filt.filter(record)
        self.assertNotIn("mypass", record.msg)

    def test_sensitive_data_filter_no_mask_normal(self):
        from platex_client.logging_utils import _SensitiveDataFilter
        filt = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "normal message", (), None)
        filt.filter(record)
        self.assertEqual(record.msg, "normal message")

    def test_sensitive_data_filter_args(self):
        from platex_client.logging_utils import _SensitiveDataFilter
        filt = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "key: %s", ("api_key=secret",), None)
        filt.filter(record)
        self.assertNotIn("secret", str(record.args))


class TestClipboardModule(unittest.TestCase):
    def test_image_hash(self):
        from platex_client.clipboard import image_hash
        h = image_hash(b"test data")
        self.assertIsInstance(h, str)
        self.assertEqual(len(h), 64)

    def test_image_hash_deterministic(self):
        from platex_client.clipboard import image_hash
        h1 = image_hash(b"test data")
        h2 = image_hash(b"test data")
        self.assertEqual(h1, h2)

    def test_image_hash_different_data(self):
        from platex_client.clipboard import image_hash
        h1 = image_hash(b"data1")
        h2 = image_hash(b"data2")
        self.assertNotEqual(h1, h2)

    def test_set_publishing_callback(self):
        from platex_client.clipboard import set_publishing_callback
        called = []
        set_publishing_callback(lambda v: called.append(v))
        self.assertEqual(len(called), 0)
        set_publishing_callback(None)


class TestParseHotkeyToVk(unittest.TestCase):
    def test_parse_ctrl_alt_1(self):
        from platex_client.win32_hotkey import _parse_hotkey_to_vk
        result = _parse_hotkey_to_vk("<ctrl>+<alt>+1")
        self.assertIsNotNone(result)
        modifiers, vk = result
        self.assertTrue(modifiers & 0x0002)
        self.assertTrue(modifiers & 0x0001)

    def test_parse_empty(self):
        from platex_client.win32_hotkey import _parse_hotkey_to_vk
        self.assertIsNone(_parse_hotkey_to_vk(""))

    def test_parse_bare_modifier(self):
        from platex_client.win32_hotkey import _parse_hotkey_to_vk
        self.assertIsNone(_parse_hotkey_to_vk("<ctrl>"))

    def test_parse_single_key(self):
        from platex_client.win32_hotkey import _parse_hotkey_to_vk
        result = _parse_hotkey_to_vk("a")
        self.assertIsNotNone(result)
        _, vk = result
        self.assertEqual(vk, 0x41)


class TestEventTypes(unittest.TestCase):
    def test_ocr_success_event(self):
        event = OcrSuccessEvent(latex="x^2", image_hash="abc", source="test")
        self.assertEqual(event.latex, "x^2")
        self.assertEqual(event.image_hash, "abc")

    def test_ocr_error_event(self):
        event = OcrErrorEvent(error="timeout", source="test")
        self.assertEqual(event.error, "timeout")

    def test_app_state_changed_event(self):
        event = AppStateChangedEvent(old_state="IDLE", new_state="RUNNING")
        self.assertEqual(event.old_state, "IDLE")
        self.assertEqual(event.new_state, "RUNNING")

    def test_config_changed_event(self):
        event = ConfigChangedEvent(payload={"key": "val"})
        self.assertEqual(event.payload["key"], "val")

    def test_hotkey_status_changed_event(self):
        event = HotkeyStatusChangedEvent(status={"running": True})
        self.assertTrue(event.status["running"])

    def test_clipboard_publishing_event(self):
        event = ClipboardPublishingEvent(is_publishing=True)
        self.assertTrue(event.is_publishing)

    def test_show_panel_event(self):
        event = ShowPanelEvent()
        self.assertIsInstance(event, Event)

    def test_shutdown_request_event(self):
        event = ShutdownRequestEvent()
        self.assertIsInstance(event, Event)


class TestGlobalEventBus(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_get_event_bus_returns_same(self):
        bus1 = get_event_bus()
        bus2 = get_event_bus()
        self.assertIs(bus1, bus2)

    def test_reset_event_bus(self):
        bus1 = get_event_bus()
        reset_event_bus()
        bus2 = get_event_bus()
        self.assertIsNot(bus1, bus2)


class TestScriptSafetyPatterns(unittest.TestCase):
    def test_all_dangerous_patterns_are_compiled(self):
        for pattern, label in _DANGEROUS_PATTERNS:
            self.assertTrue(hasattr(pattern, 'search'), f"Pattern for '{label}' is not compiled")

    def test_all_blocked_patterns_are_compiled(self):
        for pattern, label in _BLOCKED_PATTERNS:
            self.assertTrue(hasattr(pattern, 'search'), f"Pattern for '{label}' is not compiled")

    def test_blocked_is_subset_of_dangerous(self):
        dangerous_labels = {label for _, label in _DANGEROUS_PATTERNS}
        blocked_labels = {label for _, label in _BLOCKED_PATTERNS}
        self.assertTrue(blocked_labels.issubset(dangerous_labels))

    def test_pickle_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "pickle_script.py"
            path.write_text("import pickle\npickle.loads(b'x')\n", encoding="utf-8")
            _, blocked = scan_script_source(path)
            self.assertIn("pickle deserialization", blocked)

    def test_socket_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "socket_script.py"
            path.write_text("import socket\nsocket.socket()\n", encoding="utf-8")
            warnings, blocked = scan_script_source(path)
            self.assertIn("socket access", warnings)

    def test_os_environ_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "environ_script.py"
            path.write_text("import os\nos.environ['KEY'] = 'val'\n", encoding="utf-8")
            warnings, blocked = scan_script_source(path)
            self.assertIn("os.environ access", warnings)

    def test_webbrowser_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "web_script.py"
            path.write_text("import webbrowser\nwebbrowser.open('http://x')\n", encoding="utf-8")
            warnings, blocked = scan_script_source(path)
            self.assertIn("webbrowser access", warnings)

    def test_ctypes_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ctypes_script.py"
            path.write_text("import ctypes\nctypes.windll.kernel32\n", encoding="utf-8")
            warnings, _ = scan_script_source(path)
            self.assertIn("ctypes FFI access", warnings)

    def test_importlib_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "importlib_script.py"
            path.write_text("import importlib\nimportlib.import_module('os')\n", encoding="utf-8")
            warnings, _ = scan_script_source(path)
            self.assertIn("importlib.import_module()", warnings)

    def test_file_write_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "write_script.py"
            path.write_text("open('file.txt', 'w')\n", encoding="utf-8")
            warnings, _ = scan_script_source(path)
            self.assertTrue(any("file" in w for w in warnings))

    def test_requests_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "requests_script.py"
            path.write_text("import requests\nrequests.get('http://x')\n", encoding="utf-8")
            warnings, _ = scan_script_source(path)
            self.assertIn("requests HTTP call", warnings)


class TestMaxFieldLengths(unittest.TestCase):
    def test_max_field_lengths_defined(self):
        self.assertIn("image_hash", _MAX_FIELD_LENGTHS)
        self.assertIn("latex", _MAX_FIELD_LENGTHS)
        self.assertIn("source", _MAX_FIELD_LENGTHS)
        self.assertIn("status", _MAX_FIELD_LENGTHS)
        self.assertIn("error", _MAX_FIELD_LENGTHS)

    def test_max_field_lengths_reasonable(self):
        self.assertGreater(_MAX_FIELD_LENGTHS["image_hash"], 0)
        self.assertGreater(_MAX_FIELD_LENGTHS["latex"], 0)
        self.assertLessEqual(_MAX_FIELD_LENGTHS["image_hash"], 256)
        self.assertLessEqual(_MAX_FIELD_LENGTHS["status"], 64)


if __name__ == "__main__":
    unittest.main()
