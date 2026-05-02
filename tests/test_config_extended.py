from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.config import AppConfig, ConfigStore, _parse_bool, _safe_resolve_path, _validate_config_path, load_config
from platex_client.secrets import clear_all, delete_secret, get_all_keys, get_secret, has_secret, set_secret


class TestSafeResolvePath(unittest.TestCase):
    def test_empty_string_returns_none(self):
        self.assertIsNone(_safe_resolve_path("", "db_path"))

    def test_whitespace_only_returns_none(self):
        self.assertIsNone(_safe_resolve_path("   ", "db_path"))

    def test_non_string_returns_none(self):
        self.assertIsNone(_safe_resolve_path(123, "db_path"))

    def test_path_traversal_rejected(self):
        self.assertIsNone(_safe_resolve_path("../../etc/passwd", "db_path"))

    def test_valid_path_resolved(self):
        result = _safe_resolve_path("/tmp/test", "db_path")
        self.assertIsNotNone(result)
        self.assertTrue(str(result).endswith("test"))

    def test_dot_segments_rejected(self):
        self.assertIsNone(_safe_resolve_path("foo/../etc", "db_path"))


class TestValidateConfigPath(unittest.TestCase):
    def test_empty_string_returns_none(self):
        self.assertIsNone(_validate_config_path(""))

    def test_whitespace_returns_none(self):
        self.assertIsNone(_validate_config_path("   "))

    def test_path_traversal_rejected(self):
        self.assertIsNone(_validate_config_path("../../etc/passwd"))

    def test_valid_path_accepted(self):
        result = _validate_config_path("/tmp/config.yaml")
        self.assertIsNotNone(result)


class TestAppConfigSlots(unittest.TestCase):
    def test_slots_prevents_arbitrary_attributes(self):
        cfg = AppConfig()
        with self.assertRaises(AttributeError):
            cfg.arbitrary_attr = "test"

    def test_all_fields_accessible(self):
        cfg = AppConfig()
        fields = ["db_path", "script", "log_file", "interval", "isolate_mode",
                  "glm_api_key", "glm_model", "glm_base_url", "auto_start",
                  "ui_language", "language_pack"]
        for f in fields:
            self.assertTrue(hasattr(cfg, f), f"Missing field: {f}")


class TestAppConfigApplyEnvironmentMaskedValues(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_masked_api_key_not_stored(self):
        cfg = AppConfig(glm_api_key="********")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_masked_model_not_stored(self):
        cfg = AppConfig(glm_model="***")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_MODEL"))

    def test_masked_base_url_not_stored(self):
        cfg = AppConfig(glm_base_url="sk-1****")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_BASE_URL"))

    def test_partial_mask_not_stored(self):
        cfg = AppConfig(glm_api_key="sk-1****")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))


class TestLoadConfigAllFields(unittest.TestCase):
    def setUp(self):
        clear_all()
        ConfigStore.reset()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        ConfigStore.reset()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_full_config_all_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "db_path: /tmp/test_db\n"
                "script: /tmp/test_script.py\n"
                "log_file: /tmp/test.log\n"
                "interval: 2.5\n"
                "isolate_mode: true\n"
                "glm_api_key: test-key\n"
                "glm_model: glm-4\n"
                "glm_base_url: https://api.test.com\n"
                "auto_start: true\n"
                "ui_language: en\n"
                "language_pack: zh-CN\n",
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertIsNotNone(cfg.db_path)
            self.assertIsNotNone(cfg.script)
            self.assertIsNotNone(cfg.log_file)
            self.assertEqual(cfg.interval, 2.5)
            self.assertTrue(cfg.isolate_mode)
            self.assertEqual(cfg.glm_api_key, "test-key")
            self.assertEqual(cfg.glm_model, "glm-4")
            self.assertEqual(cfg.glm_base_url, "https://api.test.com")
            self.assertTrue(cfg.auto_start)
            self.assertEqual(cfg.ui_language, "en")
            self.assertEqual(cfg.language_pack, "zh-CN")

    def test_config_with_boolean_strings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "isolate_mode: 'yes'\n"
                "auto_start: 'on'\n",
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertTrue(cfg.isolate_mode)
            self.assertTrue(cfg.auto_start)

    def test_config_interval_string_number(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: '3.0'\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 3.0)

    def test_config_interval_invalid_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 'fast'\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_config_upper_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 999.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_config_exact_minimum_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0.1\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.1)

    def test_config_just_below_minimum_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0.09\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.1)


class TestConfigStoreUpdateLanguage(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_update_valid_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"ui_language": "zh-cn"})
            self.assertEqual(store.config.ui_language, "zh-cn")

    def test_update_invalid_language_keeps_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original = store.config.ui_language
            store.request_update_and_save({"ui_language": "invalid"})
            self.assertEqual(store.config.ui_language, original)

    def test_update_empty_language_keeps_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original = store.config.ui_language
            store.request_update_and_save({"ui_language": ""})
            self.assertEqual(store.config.ui_language, original)


class TestConfigStoreUpdateScriptPath(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_update_valid_script_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("def process_image(image_bytes, context): return 'test'", encoding="utf-8")
            store.request_update_and_save({"script": str(script_path)})
            self.assertIsNotNone(store.config.script)

    def test_update_traversal_script_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"script": "../../etc/passwd"})
            self.assertIsNone(store.config.script)

    def test_update_empty_script_path_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"script": ""})


class TestConfigStoreUpdateGlmFields(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()

    def tearDown(self):
        ConfigStore.reset()
        clear_all()

    def test_update_glm_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"glm_api_key": "new-key"})
            self.assertEqual(store.config.glm_api_key, "new-key")

    def test_update_glm_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"glm_model": "glm-4v"})
            self.assertEqual(store.config.glm_model, "glm-4v")

    def test_update_glm_base_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"glm_base_url": "https://new.api.com"})
            self.assertEqual(store.config.glm_base_url, "https://new.api.com")

    def test_non_string_glm_api_key_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original = store.config.glm_api_key
            store.request_update_and_save({"glm_api_key": 12345})
            self.assertEqual(store.config.glm_api_key, original)


class TestConfigStoreUpdateDbPath(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_update_valid_db_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"db_path": "/tmp/test_db"})
            self.assertIsNotNone(store.config.db_path)

    def test_update_traversal_db_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"db_path": "../../etc/passwd"})
            self.assertIsNone(store.config.db_path)

    def test_update_empty_db_path_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"db_path": ""})


class TestConfigStoreUpdateLogFilePath(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_update_valid_log_file_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"log_file": "/tmp/test.log"})
            self.assertIsNotNone(store.config.log_file)

    def test_update_traversal_log_file_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"log_file": "../../etc/log"})
            self.assertIsNone(store.config.log_file)


class TestParseBoolExtended(unittest.TestCase):
    def test_true_values(self):
        for val in ["true", "True", "TRUE", "yes", "Yes", "1", "on", "ON", "On"]:
            with self.subTest(val=val):
                self.assertTrue(_parse_bool(val))

    def test_false_values(self):
        for val in ["false", "False", "FALSE", "no", "No", "0", "off", "OFF", ""]:
            with self.subTest(val=val):
                self.assertFalse(_parse_bool(val))

    def test_bool_passthrough(self):
        self.assertIs(_parse_bool(True), True)
        self.assertIs(_parse_bool(False), False)

    def test_none_returns_false(self):
        self.assertIs(_parse_bool(None), False)

    def test_numeric_values(self):
        self.assertTrue(_parse_bool(1))
        self.assertTrue(_parse_bool(42))
        self.assertFalse(_parse_bool(0))

    def test_list_falls_through(self):
        self.assertTrue(_parse_bool([1]))
        self.assertFalse(_parse_bool([]))


if __name__ == "__main__":
    unittest.main()
