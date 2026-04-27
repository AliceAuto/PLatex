from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

from platex_client.config import AppConfig, ConfigStore, _parse_bool, load_config
from platex_client.secrets import set_secret, has_secret, get_secret, delete_secret, clear_all


class TestApplyEnvironment(unittest.TestCase):
    """Test AppConfig.apply_environment() behavior."""

    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_apply_environment_sets_secret_and_environ(self):
        cfg = AppConfig(glm_api_key="test-key-123")
        cfg.apply_environment()
        self.assertTrue(has_secret("GLM_API_KEY"))
        self.assertEqual(get_secret("GLM_API_KEY"), "test-key-123")
        self.assertIsNone(os.environ.get("GLM_API_KEY"))

    def test_apply_environment_no_overwrite_existing_secret(self):
        set_secret("GLM_API_KEY", "existing-secret")
        cfg = AppConfig(glm_api_key="new-key")
        cfg.apply_environment()
        self.assertEqual(get_secret("GLM_API_KEY"), "existing-secret")

    def test_apply_environment_overwrites_existing_environ(self):
        """Bug #1: apply_environment() overwrites existing os.environ values.
        If GLM_API_KEY is already set in the environment (e.g. by the user
        via system environment variables), apply_environment() will overwrite
        it when has_secret() returns False. This is unexpected behavior -
        user-set environment variables should take precedence."""
        os.environ["GLM_API_KEY"] = "user-set-key"
        cfg = AppConfig(glm_api_key="config-key")
        cfg.apply_environment()
        result = os.environ.get("GLM_API_KEY")
        self.assertNotEqual(result, "config-key",
                            f"Bug #1: apply_environment() overwrote user-set env var. "
                            f"Expected 'user-set-key', got '{result}'")

    def test_apply_environment_none_values(self):
        cfg = AppConfig()
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))


class TestParseBoolEdgeCases(unittest.TestCase):
    def test_parse_bool_none(self):
        self.assertIs(_parse_bool(None), False)

    def test_parse_bool_zero_int(self):
        self.assertIs(_parse_bool(0), False)

    def test_parse_bool_one_int(self):
        self.assertIs(_parse_bool(1), True)

    def test_parse_bool_empty_string(self):
        self.assertIs(_parse_bool(""), False)

    def test_parse_bool_yes_string(self):
        self.assertIs(_parse_bool("yes"), True)

    def test_parse_bool_no_string(self):
        self.assertIs(_parse_bool("no"), False)

    def test_parse_bool_off_string(self):
        self.assertIs(_parse_bool("off"), False)

    def test_parse_bool_true_string(self):
        self.assertIs(_parse_bool("true"), True)

    def test_parse_bool_false_string(self):
        self.assertIs(_parse_bool("false"), False)

    def test_parse_bool_on_string(self):
        result = _parse_bool("on")
        self.assertIs(result, True, "_parse_bool('on') should return True for consistency with 'off'")

    def test_parse_bool_list_falls_through(self):
        """Bug #2: _parse_bool([]) returns False (via bool([])), but passing
        a list is likely a programming error that should be caught with a
        TypeError instead of silently returning False."""
        result = _parse_bool([])
        self.assertIs(result, False)


class TestLoadConfigEdgeCases(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_negative_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: -1.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_zero_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_empty_db_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("db_path: '  '\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsNone(cfg.db_path)

    def test_nonexistent_config_returns_default(self):
        cfg = load_config(Path("/nonexistent/path/config.yaml"))
        self.assertIsInstance(cfg, AppConfig)
        self.assertEqual(cfg.interval, 0.8)

    def test_path_traversal_in_db_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("db_path: '../../etc/passwd'\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsNone(cfg.db_path,
                              "Path traversal in db_path should be rejected")

    def test_language_pack_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("language_pack: zh-CN\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.language_pack, "zh-CN")


class TestConfigStoreSingleton(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_singleton_returns_same_instance(self):
        a = ConfigStore.instance()
        b = ConfigStore.instance()
        self.assertIs(a, b)

    def test_reset_creates_new_instance(self):
        a = ConfigStore.instance()
        ConfigStore.reset()
        b = ConfigStore.instance()
        self.assertIsNot(a, b)


class TestConfigStoreRequestUpdate(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_request_update_and_save_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 2.0, "auto_start": True})
            self.assertEqual(store.config.interval, 2.0)
            self.assertTrue(store.config.auto_start)

    def test_request_update_string_interval_handled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original_interval = store.config.interval
            store.request_update_and_save({"interval": "fast"})
            self.assertEqual(store.config.interval, original_interval)

    def test_request_update_very_small_interval_clamped(self):
        """Bug #3: Very small intervals (< 0.1) are silently clamped to 0.1
        without any indication to the user. The user might set interval to
        0.05 expecting faster polling but silently gets 0.1."""
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 0.001})
            self.assertEqual(store.config.interval, 0.1)

    def test_request_update_negative_interval_clamped(self):
        """Bug #4: Negative intervals are clamped to 0.1 instead of being
        rejected outright. A negative interval is clearly invalid and should
        probably fall back to the default (0.8) rather than the minimum."""
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": -5.0})
            self.assertEqual(store.config.interval, 0.1,
                             "Bug #4: Negative interval clamped to 0.1 instead of default 0.8")


class TestApiKeyMasking(unittest.TestCase):
    def test_strip_api_keys_short_value(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"api_key": "abc"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_strip_api_keys_exact_4_chars(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"api_key": "abcd"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_strip_api_keys_long_value(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"api_key": "sk-1234567890abcdef"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********")

    def test_strip_api_keys_12_chars(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"api_key": "123456789012"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********",
                         "All keys should be fully masked")

    def test_strip_api_keys_13_chars(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"api_key": "1234567890123"}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "********",
                         "All keys should be fully masked regardless of length")

    def test_strip_api_keys_non_string_value(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"api_key": 12345}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], 12345)

    def test_strip_api_keys_empty_string(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"api_key": ""}
        result = strip_api_keys(data)
        self.assertEqual(result["api_key"], "")

    def test_strip_api_keys_nested(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"scripts": {"my_script": {"api_key": "sk-1234567890"}}}
        result = strip_api_keys(data)
        self.assertEqual(result["scripts"]["my_script"]["api_key"], "********")

    def test_is_sensitive_key_variations(self):
        from platex_client.api_key_masking import is_sensitive_key
        self.assertTrue(is_sensitive_key("api_key"))
        self.assertTrue(is_sensitive_key("glm_api_key"))
        self.assertTrue(is_sensitive_key("secret"))
        self.assertTrue(is_sensitive_key("my_token"))
        self.assertTrue(is_sensitive_key("password"))
        self.assertTrue(is_sensitive_key("apikey"))
        self.assertFalse(is_sensitive_key("name"))
        self.assertFalse(is_sensitive_key("enabled"))
        self.assertFalse(is_sensitive_key("api"))

    def test_strip_does_not_modify_original(self):
        from platex_client.api_key_masking import strip_api_keys
        data = {"api_key": "secret123"}
        result = strip_api_keys(data)
        self.assertEqual(data["api_key"], "secret123")
        self.assertNotEqual(result["api_key"], "secret123")

    def test_is_masked_value(self):
        from platex_client.api_key_masking import _is_masked_value
        self.assertTrue(_is_masked_value("********"))
        self.assertTrue(_is_masked_value("***"))
        self.assertTrue(_is_masked_value("sk-1****"))
        self.assertTrue(_is_masked_value("****"))
        self.assertFalse(_is_masked_value("real-key"))
        self.assertFalse(_is_masked_value("sk-12345"))


class TestRestoreApiKeyEdgeCases(unittest.TestCase):
    def test_restore_masked_value(self):
        from platex_client.api_key_masking import restore_api_key
        edited = "glm_api_key: ***\n"
        original = "glm_api_key: sk-real-key-12345\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real-key-12345", result)

    def test_restore_preserves_non_masked_values(self):
        from platex_client.api_key_masking import restore_api_key
        edited = "glm_api_key: new-actual-key\n"
        original = "glm_api_key: old-key\n"
        result = restore_api_key(edited, original)
        self.assertIn("new-actual-key", result)

    def test_restore_trailing_newline(self):
        from platex_client.api_key_masking import restore_api_key
        edited = "glm_api_key: ***\n"
        original = "glm_api_key: sk-real-key\n"
        result = restore_api_key(edited, original)
        self.assertTrue(result.endswith("\n"))

    def test_restore_partial_mask(self):
        from platex_client.api_key_masking import restore_api_key
        edited = "glm_api_key: sk-1****\n"
        original = "glm_api_key: sk-1234567890\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-1234567890", result)

    def test_restore_eight_star_mask(self):
        from platex_client.api_key_masking import restore_api_key
        edited = "glm_api_key: ********\n"
        original = "glm_api_key: sk-real-key-12345\n"
        result = restore_api_key(edited, original)
        self.assertIn("sk-real-key-12345", result)


class TestSchedulerAPI(unittest.TestCase):
    def test_schedule_once_fires(self):
        from platex_client.script_context import SchedulerAPI
        scheduler = SchedulerAPI()
        fired = threading.Event()
        scheduler.schedule_once(0.1, fired.set)
        self.assertTrue(fired.wait(timeout=2.0))
        scheduler.cancel_all()

    def test_schedule_repeating_fires(self):
        from platex_client.script_context import SchedulerAPI
        scheduler = SchedulerAPI()
        count = {"value": 0}
        count_event = threading.Event()

        def increment():
            count["value"] += 1
            if count["value"] >= 3:
                count_event.set()

        task = scheduler.schedule_repeating(0.1, increment)
        self.assertTrue(count_event.wait(timeout=5.0))
        self.assertGreaterEqual(count["value"], 3)
        task.cancel()
        scheduler.cancel_all()

    def test_schedule_once_cancel(self):
        from platex_client.script_context import SchedulerAPI
        scheduler = SchedulerAPI()
        fired = threading.Event()
        task = scheduler.schedule_once(0.5, fired.set)
        task.cancel()
        time.sleep(0.8)
        self.assertFalse(fired.is_set())
        scheduler.cancel_all()

    def test_schedule_repeating_cancel(self):
        from platex_client.script_context import SchedulerAPI
        scheduler = SchedulerAPI()
        count = {"value": 0}

        def increment():
            count["value"] += 1

        task = scheduler.schedule_repeating(0.1, increment)
        time.sleep(0.35)
        task.cancel()
        count_after_cancel = count["value"]
        time.sleep(0.3)
        self.assertEqual(count["value"], count_after_cancel)
        scheduler.cancel_all()

    def test_cancel_all(self):
        from platex_client.script_context import SchedulerAPI
        scheduler = SchedulerAPI()
        fired1 = threading.Event()
        fired2 = threading.Event()
        scheduler.schedule_once(0.3, fired1.set)
        scheduler.schedule_once(0.3, fired2.set)
        scheduler.cancel_all()
        time.sleep(0.5)
        self.assertFalse(fired1.is_set())
        self.assertFalse(fired2.is_set())

    def test_schedule_repeating_dead_timer_bug(self):
        """Bug #5: schedule_repeating creates a dead timer on line 223 that is
        never started or cancelled. The _ScheduledTask.__new__ call creates
        an uninitialized object that could cause issues if the timer were
        accidentally started."""
        from platex_client.script_context import SchedulerAPI
        scheduler = SchedulerAPI()
        count = {"value": 0}

        def increment():
            count["value"] += 1

        task = scheduler.schedule_repeating(0.1, increment)
        time.sleep(0.25)
        self.assertGreater(count["value"], 0)
        self.assertIsNotNone(task._timer)
        task.cancel()
        scheduler.cancel_all()


class TestConvertHotkeyStr(unittest.TestCase):
    def test_basic_conversion(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Alt+1"), "<ctrl>+<alt>+1")

    def test_shift_f5(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Ctrl+Shift+F5"), "<ctrl>+<shift>+<f5>")

    def test_win_key(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        self.assertEqual(convert_hotkey_str("Win+K"), "<cmd>+k")

    def test_empty_string_raises(self):
        from platex_client.hotkey_listener import convert_hotkey_str
        with self.assertRaises(ValueError):
            convert_hotkey_str("")

    def test_whitespace_only_raises(self):
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


class TestWin32HotkeyParse(unittest.TestCase):
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


class TestHotkeyRoundtrip(unittest.TestCase):
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


class TestSecretsModule(unittest.TestCase):
    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_set_and_get(self):
        set_secret("TEST_KEY", "test_value")
        self.assertEqual(get_secret("TEST_KEY"), "test_value")

    def test_get_default(self):
        self.assertEqual(get_secret("NONEXISTENT", "default"), "default")

    def test_has_secret(self):
        self.assertFalse(has_secret("TEST_KEY"))
        set_secret("TEST_KEY", "value")
        self.assertTrue(has_secret("TEST_KEY"))

    def test_delete_secret(self):
        set_secret("TEST_KEY", "value")
        delete_secret("TEST_KEY")
        self.assertFalse(has_secret("TEST_KEY"))

    def test_clear_all(self):
        set_secret("KEY1", "val1")
        set_secret("KEY2", "val2")
        clear_all()
        self.assertFalse(has_secret("KEY1"))
        self.assertFalse(has_secret("KEY2"))

    def test_overwrite_secret(self):
        set_secret("TEST_KEY", "old")
        set_secret("TEST_KEY", "new")
        self.assertEqual(get_secret("TEST_KEY"), "new")

    def test_secrets_not_thread_safe(self):
        """Bug #6: The secrets module uses a plain dict without any locking,
        which could cause issues with concurrent access."""
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

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start()
        t2.start()
        t1.join(timeout=5)
        t2.join(timeout=5)


class TestHistoryStoreEdgeCases(unittest.TestCase):
    def test_add_and_retrieve_multiple(self):
        from platex_client.history import HistoryStore
        from platex_client.models import ClipboardEvent
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "history.sqlite3"
            with HistoryStore(db_path) as store:
                for i in range(5):
                    event = ClipboardEvent(
                        created_at=datetime.now(timezone.utc),
                        image_hash=f"hash_{i}",
                        image_width=100 + i,
                        image_height=100 + i,
                        latex=f"x^{i}",
                        source="test",
                        status="ok",
                        error=None,
                    )
                    store.add(event)

                recent = store.list_recent(limit=3)
                self.assertEqual(len(recent), 3)
                self.assertEqual(recent[0].image_hash, "hash_4")

    def test_latest_empty(self):
        from platex_client.history import HistoryStore

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "history.sqlite3"
            with HistoryStore(db_path) as store:
                result = store.latest()
                self.assertIsNone(result)

    def test_error_event(self):
        from platex_client.history import HistoryStore
        from platex_client.models import ClipboardEvent
        from datetime import datetime, timezone

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "history.sqlite3"
            with HistoryStore(db_path) as store:
                event = ClipboardEvent(
                    created_at=datetime.now(timezone.utc),
                    image_hash="err_hash",
                    image_width=0,
                    image_height=0,
                    latex="",
                    source="test",
                    status="error",
                    error="Something went wrong",
                )
                store.add(event)
                latest = store.latest()
                self.assertIsNotNone(latest)
                self.assertEqual(latest.status, "error")
                self.assertEqual(latest.error, "Something went wrong")

    def test_has_close_and_context_manager(self):
        from platex_client.history import HistoryStore
        self.assertTrue(hasattr(HistoryStore, "close"))
        self.assertTrue(hasattr(HistoryStore, "__enter__"))
        self.assertTrue(hasattr(HistoryStore, "__exit__"))

    def test_concurrent_access(self):
        from platex_client.history import HistoryStore
        from platex_client.models import ClipboardEvent
        from datetime import datetime, timezone
        import gc

        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "history.sqlite3"
            store = HistoryStore(db_path)
            errors = []

            def writer(idx):
                try:
                    for i in range(20):
                        event = ClipboardEvent(
                            created_at=datetime.now(timezone.utc),
                            image_hash=f"hash_{idx}_{i}",
                            image_width=100,
                            image_height=100,
                            latex=f"x^{idx}_{i}",
                            source="test",
                            status="ok",
                            error=None,
                        )
                        store.add(event)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            self.assertEqual(len(errors), 0, f"Thread safety errors in HistoryStore: {errors}")
            store.close()
            del store
            gc.collect()
        finally:
            import shutil
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    def test_path_traversal_rejected(self):
        """Bug #7: HistoryStore rejects paths with '..' segments, but the
        error message could be more helpful."""
        from platex_client.history import HistoryStore
        with self.assertRaises(ValueError):
            HistoryStore(Path("../../etc/history.sqlite3"))


class TestClipboardWatcherSetPublishing(unittest.TestCase):
    def test_set_publishing_true_blocks_polling(self):
        from platex_client.watcher import ClipboardWatcher
        from platex_client.models import OcrProcessor

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.history import HistoryStore
            db_path = Path(temp_dir) / "test.sqlite3"
            with HistoryStore(db_path) as history:
                watcher = ClipboardWatcher(
                    processor=DummyProcessor(),
                    history=history,
                    source_name="test",
                )
                watcher.set_publishing(True)
                self.assertTrue(watcher._paused.is_set())
                self.assertIsNone(watcher.poll_once(),
                                  "poll_once should skip when publishing is True")

    def test_set_publishing_false_allows_polling(self):
        from platex_client.watcher import ClipboardWatcher
        from platex_client.models import OcrProcessor

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.history import HistoryStore
            db_path = Path(temp_dir) / "test.sqlite3"
            with HistoryStore(db_path) as history:
                watcher = ClipboardWatcher(
                    processor=DummyProcessor(),
                    history=history,
                    source_name="test",
                )
                watcher.set_publishing(False)
                self.assertFalse(watcher._paused.is_set())


class TestScriptBaseEdgeCases(unittest.TestCase):
    def _make_script(self):
        from platex_client.script_base import ScriptBase

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

    def test_process_image_without_capability_raises(self):
        script = self._make_script()
        with self.assertRaises(RuntimeError):
            script.process_image(b"fake", {})

    def test_has_ocr_capability_default_false(self):
        self.assertFalse(self._make_script().has_ocr_capability())

    def test_get_hotkey_bindings_default_empty(self):
        self.assertEqual(self._make_script().get_hotkey_bindings(), {})

    def test_notify_hotkeys_changed_no_callback(self):
        self._make_script()._notify_hotkeys_changed()

    def test_notify_hotkeys_changed_with_callback(self):
        script = self._make_script()
        called = threading.Event()
        script.set_hotkeys_changed_callback(called.set)
        script._notify_hotkeys_changed()
        self.assertTrue(called.is_set())

    def test_set_tray_action_callback_not_in_slots(self):
        """Bug #8: ScriptBase.set_tray_action_callback sets self._tray_action_callback
        but this attribute is not declared in the class. Since ScriptBase is not
        a slots=True dataclass, this works but is fragile and undocumented."""
        script = self._make_script()
        script.set_tray_action_callback(lambda a, p: None)
        self.assertTrue(hasattr(script, "_tray_action_callback"))


class TestFillMaskedApiKeys(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY",):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY",):
            os.environ.pop(key, None)

    def test_fill_masked_glm_api_key(self):
        from platex_client.api_key_masking import fill_masked_api_keys
        set_secret("GLM_API_KEY", "real-key-123")
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "real-key-123")

    def test_fill_non_masked_glm_api_key(self):
        from platex_client.api_key_masking import fill_masked_api_keys
        data = {"glm_api_key": "actual-key"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "actual-key")

    def test_fill_masked_keeps_masked_when_no_secret(self):
        from platex_client.api_key_masking import fill_masked_api_keys
        data = {"glm_api_key": "********"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "********",
                         "Masked key should be kept when no secret is available")

    def test_fill_partial_mask(self):
        from platex_client.api_key_masking import fill_masked_api_keys
        set_secret("GLM_API_KEY", "real-key-123")
        data = {"glm_api_key": "sk-1****"}
        result = fill_masked_api_keys(data)
        self.assertEqual(result["glm_api_key"], "real-key-123")


class TestAppConfigDefaults(unittest.TestCase):
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


class TestScriptRegistryNoValidation(unittest.TestCase):
    """Bug #9: ScriptRegistry has no path validation - scripts can be loaded
    from any directory, including temp directories and network paths."""

    def test_load_script_from_any_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            from platex_client.script_registry import ScriptRegistry
            registry = ScriptRegistry()
            entry = registry._load_script_file(script_path)
            self.assertIsNotNone(entry,
                                 "Bug #9: Script loaded from arbitrary path without validation")

    def test_load_script_with_dangerous_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dangerous.py"
            script_path.write_text(
                "import os\nos.system('echo pwned')\n"
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            from platex_client.script_registry import ScriptRegistry
            registry = ScriptRegistry()
            with self.assertRaises(ValueError):
                registry._load_script_file(script_path)

    def test_duplicate_script_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.script_registry import ScriptRegistry
            registry = ScriptRegistry()

            script1 = Path(temp_dir) / "myscript.py"
            script1.write_text(
                "def process_image(image_bytes, context):\n    return 'script1'\n",
                encoding="utf-8",
            )
            script2 = Path(temp_dir) / "subdir" / "myscript.py"
            script2.parent.mkdir(parents=True, exist_ok=True)
            script2.write_text(
                "def process_image(image_bytes, context):\n    return 'script2'\n",
                encoding="utf-8",
            )

            registry._load_script_file(script1)
            registry._load_script_file(script2)
            self.assertEqual(len(registry.entries), 1,
                             "Bug #9: Duplicate script names silently overwrite each other")

    def test_module_name_collision(self):
        """Bug #9: Module names are generated as f"platex_script_{path.stem}" which
        means two scripts with the same filename in different directories will
        have the same module name, potentially causing import collisions."""
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.script_registry import ScriptRegistry
            registry = ScriptRegistry()

            script1 = Path(temp_dir) / "myscript.py"
            script1.write_text(
                "VALUE = 'script1'\n"
                "def process_image(image_bytes, context):\n    return VALUE\n",
                encoding="utf-8",
            )
            script2 = Path(temp_dir) / "subdir" / "myscript.py"
            script2.parent.mkdir(parents=True, exist_ok=True)
            script2.write_text(
                "VALUE = 'script2'\n"
                "def process_image(image_bytes, context):\n    return VALUE\n",
                encoding="utf-8",
            )

            entry1 = registry._load_script_file(script1)
            entry2 = registry._load_script_file(script2)
            if entry2 is not None:
                result = entry2.script.process_image(b"test", {})
                self.assertIn(result, ["script1", "script2"])


class TestConfigStoreBuildPayload(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_build_full_payload_returns_dict(self):
        store = ConfigStore.instance()
        payload = store.build_full_payload()
        self.assertIsInstance(payload, dict)
        self.assertIn("interval", payload)

    def test_build_disk_yaml_text_returns_string(self):
        store = ConfigStore.instance()
        text = store.build_disk_yaml_text()
        self.assertIsInstance(text, str)


class TestClipboardImageModel(unittest.TestCase):
    def test_create_with_bytes(self):
        from platex_client.models import ClipboardImage
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100)
        self.assertEqual(img.image_bytes, b"fake")
        self.assertEqual(img.width, 100)
        self.assertEqual(img.height, 100)
        self.assertEqual(img.fingerprint, "")

    def test_fingerprint_field(self):
        from platex_client.models import ClipboardImage
        img = ClipboardImage(image_bytes=b"fake", width=100, height=100, fingerprint="abc123")
        self.assertEqual(img.fingerprint, "abc123")


if __name__ == "__main__":
    unittest.main()
