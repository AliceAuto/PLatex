from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from platex_client.config import (
    AppConfig,
    ConfigStore,
    _VALID_LANGUAGE_CODES,
    _is_valid_language_code,
    _parse_bool,
    _safe_resolve_path,
    _validate_config_path,
    load_config,
)
from platex_client.secrets import clear_all, delete_secret, get_secret, has_secret, set_secret


class TestAppConfigDefaultsExtended(unittest.TestCase):
    """Extended tests for AppConfig default values beyond test_config.py."""

    def test_default_interval_is_float(self):
        cfg = AppConfig()
        self.assertIsInstance(cfg.interval, float)

    def test_default_isolate_mode_is_bool(self):
        cfg = AppConfig()
        self.assertIsInstance(cfg.isolate_mode, bool)

    def test_default_auto_start_is_bool(self):
        cfg = AppConfig()
        self.assertIsInstance(cfg.auto_start, bool)

    def test_default_ui_language_is_en(self):
        cfg = AppConfig()
        self.assertEqual(cfg.ui_language, "en")

    def test_default_language_pack_is_empty_string(self):
        cfg = AppConfig()
        self.assertEqual(cfg.language_pack, "")

    def test_default_glm_fields_are_none(self):
        cfg = AppConfig()
        self.assertIsNone(cfg.glm_api_key)
        self.assertIsNone(cfg.glm_model)
        self.assertIsNone(cfg.glm_base_url)

    def test_default_path_fields_are_none(self):
        cfg = AppConfig()
        self.assertIsNone(cfg.db_path)
        self.assertIsNone(cfg.script)
        self.assertIsNone(cfg.log_file)

    def test_custom_construction(self):
        cfg = AppConfig(
            db_path=Path("/tmp/db"),
            script=Path("/tmp/script.py"),
            log_file=Path("/tmp/log.txt"),
            interval=1.5,
            isolate_mode=True,
            glm_api_key="key",
            glm_model="model",
            glm_base_url="https://api.test.com",
            auto_start=True,
            ui_language="zh-cn",
            language_pack="custom",
        )
        self.assertEqual(cfg.db_path, Path("/tmp/db"))
        self.assertEqual(cfg.interval, 1.5)
        self.assertTrue(cfg.isolate_mode)
        self.assertEqual(cfg.glm_api_key, "key")
        self.assertEqual(cfg.ui_language, "zh-cn")
        self.assertEqual(cfg.language_pack, "custom")


class TestAppConfigApplyEnvironmentMaskedValues(unittest.TestCase):
    """Extended tests for apply_environment with masked values."""

    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_masked_api_key_with_asterisks(self):
        cfg = AppConfig(glm_api_key="********")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_masked_model_with_partial_mask(self):
        cfg = AppConfig(glm_model="gl****")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_MODEL"))

    def test_masked_base_url_with_prefix_mask(self):
        cfg = AppConfig(glm_base_url="sk-****")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_BASE_URL"))

    def test_all_three_masked_simultaneously(self):
        cfg = AppConfig(
            glm_api_key="********",
            glm_model="***",
            glm_base_url="sk-1****",
        )
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))
        self.assertFalse(has_secret("GLM_MODEL"))
        self.assertFalse(has_secret("GLM_BASE_URL"))

    def test_mixed_masked_and_unmasked(self):
        cfg = AppConfig(
            glm_api_key="real-key",
            glm_model="***",
            glm_base_url="https://api.test.com",
        )
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))
        self.assertFalse(has_secret("GLM_MODEL"))
        self.assertFalse(has_secret("GLM_BASE_URL"))

    def test_apply_environment_does_not_modify_existing_secret(self):
        set_secret("GLM_API_KEY", "existing-key")
        cfg = AppConfig(glm_api_key="new-key")
        cfg.apply_environment()
        self.assertEqual(get_secret("GLM_API_KEY"), "existing-key")

    def test_apply_environment_does_not_set_secrets(self):
        cfg = AppConfig(glm_api_key="fresh-key")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_apply_environment_empty_string_not_stored(self):
        cfg = AppConfig(glm_api_key="")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_apply_environment_none_values_not_stored(self):
        cfg = AppConfig()
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))
        self.assertFalse(has_secret("GLM_MODEL"))
        self.assertFalse(has_secret("GLM_BASE_URL"))


class TestLoadConfigTomlLikeFiles(unittest.TestCase):
    """Test load_config with various file formats and edge cases."""

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

    def test_load_json_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"interval": 2.0, "isolate_mode": True, "auto_start": False}),
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 2.0)
            self.assertTrue(cfg.isolate_mode)
            self.assertFalse(cfg.auto_start)

    def test_load_yaml_config_with_all_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "db_path: /tmp/test_db\n"
                "script: /tmp/test_script.py\n"
                "log_file: /tmp/test.log\n"
                "interval: 1.5\n"
                "isolate_mode: true\n"
                "glm_api_key: test-key\n"
                "glm_model: glm-4\n"
                "glm_base_url: https://api.test.com\n"
                "auto_start: true\n"
                "ui_language: en\n"
                "language_pack: custom\n",
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertIsNotNone(cfg.db_path)
            self.assertIsNotNone(cfg.script)
            self.assertIsNotNone(cfg.log_file)
            self.assertEqual(cfg.interval, 1.5)
            self.assertTrue(cfg.isolate_mode)
            self.assertEqual(cfg.glm_api_key, "test-key")
            self.assertEqual(cfg.glm_model, "glm-4")
            self.assertEqual(cfg.glm_base_url, "https://api.test.com")
            self.assertTrue(cfg.auto_start)
            self.assertEqual(cfg.ui_language, "en")
            self.assertEqual(cfg.language_pack, "custom")

    def test_load_empty_yaml_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("---\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)
            self.assertFalse(cfg.isolate_mode)
            self.assertEqual(cfg.ui_language, "en")

    def test_load_nonexistent_returns_defaults(self):
        cfg = load_config(Path("/nonexistent/path/config.yaml"))
        self.assertIsInstance(cfg, AppConfig)
        self.assertEqual(cfg.interval, 0.8)

    def test_load_malformed_yaml_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(":\n  :\n    - invalid: [yaml: content", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_load_non_dict_payload_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_load_json_with_invalid_interval_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"interval": "fast"}),
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_load_json_with_negative_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"interval": -5.0}),
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)


class TestConfigStorePayloadBuilding(unittest.TestCase):
    """Extended tests for ConfigStore payload building methods."""

    def setUp(self):
        ConfigStore.reset()

    def tearDown(self):
        ConfigStore.reset()

    def test_build_full_payload_returns_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            payload1 = store.build_full_payload()
            payload2 = store.build_full_payload()
            self.assertIsNot(payload1, payload2)

    def test_build_full_payload_reflects_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 3.0})
            payload = store.build_full_payload()
            self.assertEqual(payload["interval"], 3.0)

    def test_build_disk_yaml_text_is_valid_yaml(self):
        import yaml
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            text = store.build_disk_yaml_text()
            parsed = yaml.safe_load(text)
            self.assertIsInstance(parsed, dict)

    def test_build_disk_yaml_text_preserves_api_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"glm_api_key": "secret-key-12345"})
            text = store.build_disk_yaml_text()
            self.assertIn("secret-key-12345", text)

    def test_build_full_payload_contains_expected_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            payload = store.build_full_payload()
            expected_keys = {
                "db_path", "script", "log_file", "interval",
                "isolate_mode", "glm_api_key", "glm_model",
                "glm_base_url", "auto_start", "ui_language",
            }
            self.assertTrue(expected_keys.issubset(set(payload.keys())))

    def test_request_update_and_save_persists_to_disk(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir, config_file_path
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 5.0, "auto_start": True})
            cfg_path = config_file_path()
            self.assertTrue(cfg_path.exists())
            import yaml
            saved = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["interval"], 5.0)
            self.assertTrue(saved["auto_start"])

    def test_request_update_concurrent_safety(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            errors = []

            def updater(val):
                try:
                    store.request_update_and_save({"interval": val})
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=updater, args=(float(i) * 0.5 + 0.1,)) for i in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)
            self.assertEqual(len(errors), 0, f"Concurrent update errors: {errors}")


class TestSafeResolvePathExtended(unittest.TestCase):
    """Extended tests for _safe_resolve_path with various inputs."""

    def test_valid_absolute_path(self):
        result = _safe_resolve_path("/tmp/test_db", "db_path")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, Path)

    def test_valid_relative_path(self):
        result = _safe_resolve_path("data/test_db", "db_path")
        self.assertIsNotNone(result)

    def test_path_with_spaces(self):
        result = _safe_resolve_path("/tmp/my path/test", "db_path")
        self.assertIsNotNone(result)

    def test_path_traversal_with_double_dot(self):
        self.assertIsNone(_safe_resolve_path("../../etc/passwd", "db_path"))

    def test_path_traversal_mixed(self):
        self.assertIsNone(_safe_resolve_path("foo/../etc", "db_path"))

    def test_empty_string(self):
        self.assertIsNone(_safe_resolve_path("", "db_path"))

    def test_whitespace_only(self):
        self.assertIsNone(_safe_resolve_path("   ", "db_path"))

    def test_none_value(self):
        self.assertIsNone(_safe_resolve_path(None, "db_path"))

    def test_integer_value(self):
        self.assertIsNone(_safe_resolve_path(42, "db_path"))

    def test_list_value(self):
        self.assertIsNone(_safe_resolve_path(["/tmp/test"], "db_path"))

    def test_path_with_leading_whitespace(self):
        result = _safe_resolve_path("  /tmp/test  ", "db_path")
        self.assertIsNotNone(result)

    def test_path_with_only_dots(self):
        result = _safe_resolve_path(".", "db_path")
        self.assertIsNotNone(result)

    def test_field_name_does_not_affect_result(self):
        result1 = _safe_resolve_path("/tmp/test", "db_path")
        result2 = _safe_resolve_path("/tmp/test", "script")
        self.assertEqual(result1, result2)


class TestValidateConfigPathEdgeCases(unittest.TestCase):
    """Extended edge case tests for _validate_config_path."""

    def test_empty_string(self):
        self.assertIsNone(_validate_config_path(""))

    def test_whitespace_only(self):
        self.assertIsNone(_validate_config_path("   "))

    def test_path_traversal_rejected(self):
        self.assertIsNone(_validate_config_path("../../etc/passwd"))

    def test_valid_path_accepted(self):
        result = _validate_config_path("/tmp/config.yaml")
        self.assertIsNotNone(result)

    def test_path_with_leading_trailing_whitespace_stripped(self):
        result = _validate_config_path("  /tmp/config.yaml  ")
        self.assertIsNotNone(result)

    def test_path_with_double_dot_in_middle_rejected(self):
        self.assertIsNone(_validate_config_path("foo/../bar"))

    def test_simple_filename(self):
        result = _validate_config_path("config.yaml")
        self.assertIsNotNone(result)

    def test_deeply_nested_path(self):
        result = _validate_config_path("/a/b/c/d/e/config.yaml")
        self.assertIsNotNone(result)


class TestLanguageCodeValidation(unittest.TestCase):
    """Tests for language code validation."""

    def test_valid_en(self):
        self.assertTrue(_is_valid_language_code("en"))

    def test_valid_zh_cn(self):
        self.assertTrue(_is_valid_language_code("zh-cn"))

    def test_invalid_code(self):
        self.assertFalse(_is_valid_language_code("fr"))

    def test_invalid_empty(self):
        self.assertFalse(_is_valid_language_code(""))

    def test_invalid_uppercase(self):
        self.assertFalse(_is_valid_language_code("EN"))

    def test_valid_language_codes_set(self):
        self.assertEqual(_VALID_LANGUAGE_CODES, {"en", "zh-cn"})

    def test_load_config_invalid_language_defaults_to_en(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("ui_language: fr\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.ui_language, "en")

    def test_load_config_uppercase_language_defaults_to_en(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("ui_language: EN\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.ui_language, "en")

    def test_load_config_zh_cn_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("ui_language: zh-cn\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.ui_language, "zh-cn")


class TestIntervalClampingBoundaries(unittest.TestCase):
    """Tests for interval clamping at exact boundaries."""

    def test_exact_minimum_0_1(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0.1\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.1)

    def test_just_below_minimum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0.09\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.1)

    def test_exact_maximum_60(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 60.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_just_above_maximum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 60.01\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_zero_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_negative_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: -1.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_very_large_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 9999.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_config_store_interval_clamping_min(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 0.001})
            self.assertEqual(store.config.interval, 0.1)

    def test_config_store_interval_clamping_max(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 100.0})
            self.assertEqual(store.config.interval, 60.0)

    def test_config_store_interval_exact_boundaries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 0.1})
            self.assertEqual(store.config.interval, 0.1)
            store.request_update_and_save({"interval": 60.0})
            self.assertEqual(store.config.interval, 60.0)


class TestParseBoolExtended(unittest.TestCase):
    """Extended _parse_bool tests beyond test_config.py."""

    def test_all_false_string_variants(self):
        for val in ["false", "0", "no", "off", ""]:
            with self.subTest(val=val):
                self.assertFalse(_parse_bool(val))

    def test_all_true_string_variants(self):
        for val in ["true", "1", "yes", "on", "anything", "maybe"]:
            with self.subTest(val=val):
                self.assertTrue(_parse_bool(val))

    def test_bool_passthrough(self):
        self.assertIs(_parse_bool(True), True)
        self.assertIs(_parse_bool(False), False)

    def test_none_returns_false(self):
        self.assertFalse(_parse_bool(None))

    def test_integer_values(self):
        self.assertTrue(_parse_bool(1))
        self.assertTrue(_parse_bool(42))
        self.assertFalse(_parse_bool(0))

    def test_float_values(self):
        self.assertTrue(_parse_bool(0.5))
        self.assertFalse(_parse_bool(0.0))

    def test_list_values(self):
        self.assertTrue(_parse_bool([1]))
        self.assertFalse(_parse_bool([]))

    def test_case_insensitive(self):
        self.assertTrue(_parse_bool("TRUE"))
        self.assertTrue(_parse_bool("True"))
        self.assertFalse(_parse_bool("FALSE"))
        self.assertFalse(_parse_bool("OFF"))
        self.assertTrue(_parse_bool("ON"))
        self.assertTrue(_parse_bool("YES"))
        self.assertFalse(_parse_bool("NO"))


if __name__ == "__main__":
    unittest.main()
