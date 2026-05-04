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
    _candidate_config_paths,
    _is_valid_language_code,
    _parse_bool,
    _safe_resolve_path,
    _validate_config_path,
    load_config,
)
from platex_client.secrets import clear_all, get_secret, has_secret, set_secret


class TestParseBool(unittest.TestCase):
    def test_true_bool(self):
        self.assertIs(_parse_bool(True), True)

    def test_false_bool(self):
        self.assertIs(_parse_bool(False), False)

    def test_string_true(self):
        self.assertIs(_parse_bool("true"), True)

    def test_string_True(self):
        self.assertIs(_parse_bool("True"), True)

    def test_string_TRUE(self):
        self.assertIs(_parse_bool("TRUE"), True)

    def test_string_yes(self):
        self.assertIs(_parse_bool("yes"), True)

    def test_string_Yes(self):
        self.assertIs(_parse_bool("Yes"), True)

    def test_string_on(self):
        self.assertIs(_parse_bool("on"), True)

    def test_string_ON(self):
        self.assertIs(_parse_bool("ON"), True)

    def test_string_1(self):
        self.assertIs(_parse_bool("1"), True)

    def test_string_false(self):
        self.assertIs(_parse_bool("false"), False)

    def test_string_False(self):
        self.assertIs(_parse_bool("False"), False)

    def test_string_no(self):
        self.assertIs(_parse_bool("no"), False)

    def test_string_off(self):
        self.assertIs(_parse_bool("off"), False)

    def test_string_OFF(self):
        self.assertIs(_parse_bool("OFF"), False)

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

    def test_int_42(self):
        self.assertIs(_parse_bool(42), True)

    def test_float_1_0(self):
        self.assertIs(_parse_bool(1.0), True)

    def test_float_0_0(self):
        self.assertIs(_parse_bool(0.0), False)

    def test_list_falls_through(self):
        self.assertIs(_parse_bool([]), False)

    def test_non_empty_list_falls_through(self):
        self.assertIs(_parse_bool([1]), True)

    def test_dict_falls_through(self):
        self.assertIs(_parse_bool({}), False)

    def test_non_empty_dict_falls_through(self):
        self.assertIs(_parse_bool({"a": 1}), True)

    def test_random_string(self):
        self.assertIs(_parse_bool("random"), True)

    def test_string_with_spaces(self):
        self.assertIs(_parse_bool("  true  "), True)


class TestValidateConfigPath(unittest.TestCase):
    def test_normal_path(self):
        result = _validate_config_path("/some/normal/path")
        self.assertIsNotNone(result)

    def test_empty_string(self):
        result = _validate_config_path("")
        self.assertIsNone(result)

    def test_whitespace_only(self):
        result = _validate_config_path("   ")
        self.assertIsNone(result)

    def test_path_traversal_rejected(self):
        result = _validate_config_path("../../etc/passwd")
        self.assertIsNone(result)

    def test_path_with_dotdot_in_middle(self):
        result = _validate_config_path("/some/../etc/passwd")
        self.assertIsNone(result)

    def test_normal_relative_path(self):
        result = _validate_config_path("config.yaml")
        self.assertIsNotNone(result)


class TestSafeResolvePath(unittest.TestCase):
    def test_normal_path(self):
        result = _safe_resolve_path("/some/path", "test_field")
        self.assertIsNotNone(result)

    def test_empty_string(self):
        result = _safe_resolve_path("", "test_field")
        self.assertIsNone(result)

    def test_whitespace_only(self):
        result = _safe_resolve_path("   ", "test_field")
        self.assertIsNone(result)

    def test_non_string_input(self):
        result = _safe_resolve_path(123, "test_field")
        self.assertIsNone(result)

    def test_path_traversal(self):
        result = _safe_resolve_path("../../etc/passwd", "db_path")
        self.assertIsNone(result)

    def test_none_input(self):
        result = _safe_resolve_path(None, "test_field")
        self.assertIsNone(result)


class TestIsValidLanguageCode(unittest.TestCase):
    def test_en(self):
        self.assertTrue(_is_valid_language_code("en"))

    def test_zh_cn(self):
        self.assertTrue(_is_valid_language_code("zh-cn"))

    def test_invalid_code(self):
        self.assertFalse(_is_valid_language_code("xx-yy"))

    def test_empty_string(self):
        self.assertFalse(_is_valid_language_code(""))

    def test_uppercase(self):
        self.assertFalse(_is_valid_language_code("EN"))

    def test_zh_CN(self):
        self.assertFalse(_is_valid_language_code("zh-CN"))


class TestCandidateConfigPaths(unittest.TestCase):
    def test_with_explicit_path(self):
        paths = _candidate_config_paths(Path("/my/config.yaml"))
        self.assertEqual(paths, [Path("/my/config.yaml")])

    def test_without_path_returns_list(self):
        paths = _candidate_config_paths(None)
        self.assertIsInstance(paths, list)
        self.assertGreater(len(paths), 0)


class TestLoadConfigYaml(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_full_yaml_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                "glm_api_key: yaml-key\n"
                "glm_model: glm-test-model\n"
                "glm_base_url: https://example.invalid/v1\n"
                "interval: 1.25\n"
                "isolate_mode: true\n"
                "auto_start: true\n"
                "ui_language: en\n"
                "language_pack: zh-CN\n",
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertEqual(cfg.glm_api_key, "yaml-key")
            self.assertEqual(cfg.glm_model, "glm-test-model")
            self.assertEqual(cfg.glm_base_url, "https://example.invalid/v1")
            self.assertEqual(cfg.interval, 1.25)
            self.assertTrue(cfg.isolate_mode)
            self.assertTrue(cfg.auto_start)
            self.assertEqual(cfg.ui_language, "en")
            self.assertEqual(cfg.language_pack, "zh-CN")

    def test_minimal_yaml_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 2.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 2.0)
            self.assertIsNone(cfg.glm_api_key)

    def test_empty_yaml_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("---\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_null_yaml_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("---\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsInstance(cfg, AppConfig)

    def test_nonexistent_config_returns_default(self):
        cfg = load_config(Path("/nonexistent/path/config.yaml"))
        self.assertIsInstance(cfg, AppConfig)
        self.assertEqual(cfg.interval, 0.8)
        self.assertIsNone(cfg.glm_api_key)
        self.assertFalse(cfg.isolate_mode)
        self.assertFalse(cfg.auto_start)

    def test_negative_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: -1.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_zero_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_very_small_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0.05\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.1)

    def test_interval_at_minimum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0.1\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.1)

    def test_interval_at_maximum(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 60.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_interval_over_maximum_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 100.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_invalid_interval_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: not_a_number\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_malformed_yaml_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(":\n  :\n    - invalid: [yaml: content", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_non_dict_yaml_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_path_traversal_in_db_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("db_path: '../../etc/passwd'\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsNone(cfg.db_path)

    def test_empty_db_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("db_path: '  '\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsNone(cfg.db_path)

    def test_path_traversal_in_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("script: '../../etc/malicious.py'\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsNone(cfg.script)

    def test_path_traversal_in_log_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("log_file: '../../var/log/hack.log'\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertIsNone(cfg.log_file)

    def test_invalid_language_defaults_to_en(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("ui_language: xx-yy\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.ui_language, "en")

    def test_valid_language_zh_cn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("ui_language: zh-cn\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.ui_language, "zh-cn")

    def test_language_pack_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("language_pack: custom-pack\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.language_pack, "custom-pack")


class TestLoadConfigJson(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_json_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"interval": 2.0, "isolate_mode": True}),
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 2.0)
            self.assertTrue(cfg.isolate_mode)

    def test_json_config_with_api_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text(
                json.dumps({"glm_api_key": "json-key", "glm_model": "glm-4"}),
                encoding="utf-8",
            )
            cfg = load_config(config_path)
            self.assertEqual(cfg.glm_api_key, "json-key")
            self.assertEqual(cfg.glm_model, "glm-4")

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("{invalid json", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_json_non_dict_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)


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

    def test_custom_values(self):
        cfg = AppConfig(
            db_path=Path("/tmp/db"),
            interval=2.0,
            isolate_mode=True,
            glm_api_key="key123",
            auto_start=True,
            ui_language="zh-cn",
        )
        self.assertEqual(cfg.db_path, Path("/tmp/db"))
        self.assertEqual(cfg.interval, 2.0)
        self.assertTrue(cfg.isolate_mode)
        self.assertEqual(cfg.glm_api_key, "key123")
        self.assertTrue(cfg.auto_start)
        self.assertEqual(cfg.ui_language, "zh-cn")


class TestAppConfigApplyEnvironment(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_apply_does_not_set_secrets(self):
        cfg = AppConfig(glm_api_key="key1", glm_model="model1", glm_base_url="url1")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))
        self.assertFalse(has_secret("GLM_MODEL"))
        self.assertFalse(has_secret("GLM_BASE_URL"))

    def test_apply_does_not_leak_to_environ(self):
        cfg = AppConfig(glm_api_key="secret1", glm_model="model1", glm_base_url="url1")
        cfg.apply_environment()
        self.assertIsNone(os.environ.get("GLM_API_KEY"))
        self.assertIsNone(os.environ.get("GLM_MODEL"))
        self.assertIsNone(os.environ.get("GLM_BASE_URL"))

    def test_apply_does_not_overwrite_existing_secret(self):
        set_secret("GLM_API_KEY", "existing")
        cfg = AppConfig(glm_api_key="new")
        cfg.apply_environment()
        self.assertEqual(get_secret("GLM_API_KEY"), "existing")

    def test_apply_with_none_values(self):
        cfg = AppConfig()
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))
        self.assertFalse(has_secret("GLM_MODEL"))
        self.assertFalse(has_secret("GLM_BASE_URL"))

    def test_apply_with_masked_value_skipped(self):
        cfg = AppConfig(glm_api_key="********")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_apply_with_partial_mask_skipped(self):
        cfg = AppConfig(glm_api_key="sk-1****")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))

    def test_apply_does_not_overwrite_existing_environ(self):
        os.environ["GLM_API_KEY"] = "user-set-key"
        cfg = AppConfig(glm_api_key="config-key")
        cfg.apply_environment()
        self.assertEqual(os.environ.get("GLM_API_KEY"), "user-set-key")

    def test_apply_all_three_secrets_not_set(self):
        set_secret("GLM_MODEL", "existing-model")
        cfg = AppConfig(glm_api_key="new-key", glm_model="new-model", glm_base_url="new-url")
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))
        self.assertEqual(get_secret("GLM_MODEL"), "existing-model")
        self.assertFalse(has_secret("GLM_BASE_URL"))


class TestConfigStoreSingleton(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()

    def tearDown(self):
        ConfigStore.reset()
        clear_all()

    def test_singleton_returns_same_instance(self):
        a = ConfigStore.instance()
        b = ConfigStore.instance()
        self.assertIs(a, b)

    def test_reset_creates_new_instance(self):
        a = ConfigStore.instance()
        ConfigStore.reset()
        b = ConfigStore.instance()
        self.assertIsNot(a, b)

    def test_singleton_thread_safety(self):
        instances = []
        errors = []

        def get_instance():
            try:
                inst = ConfigStore.instance()
                instances.append(id(inst))
            except Exception as e:
                errors.append(e)

        ConfigStore.reset()
        threads = [threading.Thread(target=get_instance) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(set(instances)), 1)


class TestConfigStoreRequestUpdate(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()

    def tearDown(self):
        ConfigStore.reset()
        clear_all()

    def test_update_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 2.0})
            self.assertEqual(store.config.interval, 2.0)

    def test_update_auto_start(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"auto_start": True})
            self.assertTrue(store.config.auto_start)

    def test_update_isolate_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"isolate_mode": True})
            self.assertTrue(store.config.isolate_mode)

    def test_string_interval_rejected(self):
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

    def test_over_max_interval_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 100.0})
            self.assertEqual(store.config.interval, 60.0)

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
            store.request_update_and_save({"glm_model": "glm-4"})
            self.assertEqual(store.config.glm_model, "glm-4")

    def test_update_glm_base_url(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"glm_base_url": "https://api.new.com"})
            self.assertEqual(store.config.glm_base_url, "https://api.new.com")

    def test_path_traversal_in_script_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"script": "../../etc/malicious.py"})
            self.assertNotEqual(str(store.config.script), "../../etc/malicious.py")

    def test_path_traversal_in_db_path_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"db_path": "../../etc/hack.db"})
            self.assertIsNone(store.config.db_path)

    def test_concurrent_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
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


class TestConfigStoreBuildPayload(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()

    def tearDown(self):
        ConfigStore.reset()
        clear_all()

    def test_build_full_payload_returns_dict(self):
        store = ConfigStore.instance()
        payload = store.build_full_payload()
        self.assertIsInstance(payload, dict)
        self.assertIn("interval", payload)
        self.assertIn("isolate_mode", payload)
        self.assertIn("auto_start", payload)
        self.assertIn("ui_language", payload)

    def test_build_disk_yaml_text_returns_string(self):
        store = ConfigStore.instance()
        text = store.build_disk_yaml_text()
        self.assertIsInstance(text, str)

    def test_build_full_payload_after_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 3.0})
            payload = store.build_full_payload()
            self.assertEqual(payload["interval"], 3.0)


class TestConfigStoreSaveAndReload(unittest.TestCase):
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

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir, config_file_path
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 3.0, "auto_start": True})
            saved_path = config_file_path()
            self.assertTrue(saved_path.exists())
            reloaded = load_config(saved_path)
            self.assertEqual(reloaded.interval, 3.0)
            self.assertTrue(reloaded.auto_start)


if __name__ == "__main__":
    unittest.main()
