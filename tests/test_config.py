from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from platex_client.config import (
    AppConfig,
    ConfigStore,
    _parse_bool,
    _safe_resolve_path,
    _validate_config_path,
    load_config,
)
from platex_client.secrets import clear_all


class TestParseBool(unittest.TestCase):
    def test_bool_true(self):
        self.assertIs(_parse_bool(True), True)

    def test_bool_false(self):
        self.assertIs(_parse_bool(False), False)

    def test_string_true(self):
        self.assertIs(_parse_bool("true"), True)

    def test_string_false(self):
        self.assertIs(_parse_bool("false"), False)

    def test_string_yes(self):
        self.assertIs(_parse_bool("yes"), True)

    def test_string_no(self):
        self.assertIs(_parse_bool("no"), False)

    def test_string_on(self):
        self.assertIs(_parse_bool("on"), True)

    def test_string_off(self):
        self.assertIs(_parse_bool("off"), False)

    def test_string_1(self):
        self.assertIs(_parse_bool("1"), True)

    def test_string_0(self):
        self.assertIs(_parse_bool("0"), False)

    def test_empty_string(self):
        self.assertIs(_parse_bool(""), False)

    def test_none(self):
        self.assertIs(_parse_bool(None), False)

    def test_int_1(self):
        self.assertIs(_parse_bool(1), True)

    def test_int_0(self):
        self.assertIs(_parse_bool(0), False)

    def test_case_insensitive(self):
        self.assertIs(_parse_bool("TRUE"), True)
        self.assertIs(_parse_bool("False"), False)
        self.assertIs(_parse_bool("ON"), True)
        self.assertIs(_parse_bool("OFF"), False)

    def test_list_falls_through(self):
        self.assertIs(_parse_bool([]), False)


class TestValidateConfigPath(unittest.TestCase):
    def test_valid_path(self):
        result = _validate_config_path("/some/valid/path")
        self.assertIsNotNone(result)

    def test_empty_string(self):
        result = _validate_config_path("")
        self.assertIsNone(result)

    def test_whitespace_only(self):
        result = _validate_config_path("   ")
        self.assertIsNone(result)

    def test_path_traversal(self):
        result = _validate_config_path("../../etc/passwd")
        self.assertIsNone(result)


class TestSafeResolvePath(unittest.TestCase):
    def test_valid_path(self):
        result = _safe_resolve_path("/some/path", "test")
        self.assertIsNotNone(result)

    def test_empty_string(self):
        result = _safe_resolve_path("", "test")
        self.assertIsNone(result)

    def test_whitespace(self):
        result = _safe_resolve_path("   ", "test")
        self.assertIsNone(result)

    def test_non_string(self):
        result = _safe_resolve_path(123, "test")
        self.assertIsNone(result)

    def test_path_traversal(self):
        result = _safe_resolve_path("../../etc/passwd", "test")
        self.assertIsNone(result)


class TestLoadConfig(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_load_yaml_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "glm_api_key: yaml-key\nglm_model: glm-test-model\n"
                "glm_base_url: https://example.invalid/v1\ninterval: 1.25\n",
                encoding="utf-8",
            )
            config = load_config(config_path)
            config.apply_environment()
            self.assertEqual(config.glm_api_key, "yaml-key")
            self.assertEqual(config.glm_model, "glm-test-model")
            self.assertEqual(config.interval, 1.25)

    def test_load_nonexistent_returns_default(self):
        cfg = load_config(Path("/nonexistent/path/config.yaml"))
        self.assertIsInstance(cfg, AppConfig)
        self.assertEqual(cfg.interval, 0.8)

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

    def test_very_small_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0.01\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.1)

    def test_very_large_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 100.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_invalid_interval_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: fast\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_json_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text('{"interval": 2.0, "isolate_mode": true}', encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 2.0)
            self.assertTrue(cfg.isolate_mode)

    def test_malformed_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(":\n  :\n    - invalid: [yaml: content", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_non_dict_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_null_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("---\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_empty_db_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("db_path: '  '\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsNone(cfg.db_path)

    def test_path_traversal_in_db_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("db_path: '../../etc/passwd'\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsNone(cfg.db_path)

    def test_invalid_language_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("ui_language: xx-yy\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.ui_language, "en")

    def test_valid_language_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("ui_language: zh-cn\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.ui_language, "zh-cn")

    def test_language_pack_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("language_pack: zh-CN\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.language_pack, "zh-CN")

    def test_isolate_mode_true(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("isolate_mode: true\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertTrue(cfg.isolate_mode)

    def test_auto_start_true(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("auto_start: true\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertTrue(cfg.auto_start)


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
        self.assertEqual(cfg.language_pack, "")


class TestAppConfigApplyEnvironment(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_apply_sets_secrets(self):
        cfg = AppConfig(glm_api_key="test-key")
        cfg.apply_environment()
        from platex_client.secrets import get_secret
        self.assertEqual(get_secret("GLM_API_KEY"), "test-key")

    def test_apply_does_not_leak_to_environ(self):
        cfg = AppConfig(glm_api_key="secret1", glm_model="model1", glm_base_url="https://api.test.com")
        cfg.apply_environment()
        self.assertIsNone(os.environ.get("GLM_API_KEY"))
        self.assertIsNone(os.environ.get("GLM_MODEL"))
        self.assertIsNone(os.environ.get("GLM_BASE_URL"))

    def test_apply_none_values(self):
        cfg = AppConfig()
        cfg.apply_environment()
        from platex_client.secrets import has_secret
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_apply_does_not_overwrite_existing_secret(self):
        from platex_client.secrets import set_secret, get_secret
        set_secret("GLM_API_KEY", "existing")
        cfg = AppConfig(glm_api_key="new")
        cfg.apply_environment()
        self.assertEqual(get_secret("GLM_API_KEY"), "existing")

    def test_apply_masked_value_skipped(self):
        cfg = AppConfig(glm_api_key="********")
        cfg.apply_environment()
        from platex_client.secrets import has_secret
        self.assertFalse(has_secret("GLM_API_KEY"))


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

    def test_update_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 2.0})
            self.assertEqual(store.config.interval, 2.0)

    def test_update_string_interval_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original = store.config.interval
            store.request_update_and_save({"interval": "fast"})
            self.assertEqual(store.config.interval, original)

    def test_very_small_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 0.001})
            self.assertEqual(store.config.interval, 0.1)

    def test_negative_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": -5.0})
            self.assertEqual(store.config.interval, 0.1)

    def test_large_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 100.0})
            self.assertEqual(store.config.interval, 60.0)

    def test_update_auto_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"auto_start": True})
            self.assertTrue(store.config.auto_start)

    def test_update_ui_language(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"ui_language": "zh-cn"})
            self.assertEqual(store.config.ui_language, "zh-cn")

    def test_invalid_ui_language_kept(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original = store.config.ui_language
            store.request_update_and_save({"ui_language": "invalid"})
            self.assertEqual(store.config.ui_language, original)


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

    def test_build_full_payload_contains_keys(self):
        store = ConfigStore.instance()
        payload = store.build_full_payload()
        expected_keys = {"interval", "isolate_mode", "auto_start", "ui_language"}
        self.assertTrue(expected_keys.issubset(set(payload.keys())))


if __name__ == "__main__":
    unittest.main()
