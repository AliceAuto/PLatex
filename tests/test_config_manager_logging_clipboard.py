from __future__ import annotations

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from platex_client.config_manager import (
    ConfigManager,
    deep_merge,
)
from platex_client.logging_utils import _SensitiveDataFilter


class TestDeepMerge(unittest.TestCase):
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"], 3)
        self.assertEqual(result["c"], 4)

    def test_nested_merge(self):
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 99}, "e": 5}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"]["c"], 99)
        self.assertEqual(result["b"]["d"], 3)
        self.assertEqual(result["e"], 5)

    def test_does_not_modify_original(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        result = deep_merge(base, override)
        self.assertNotIn("y", base["a"])

    def test_override_dict_with_non_dict(self):
        base = {"a": {"x": 1}}
        override = {"a": "string"}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], "string")

    def test_override_non_dict_with_dict(self):
        base = {"a": "string"}
        override = {"a": {"x": 1}}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], {"x": 1})

    def test_empty_base(self):
        result = deep_merge({}, {"a": 1})
        self.assertEqual(result, {"a": 1})

    def test_empty_override(self):
        result = deep_merge({"a": 1}, {})
        self.assertEqual(result, {"a": 1})

    def test_both_empty(self):
        result = deep_merge({}, {})
        self.assertEqual(result, {})

    def test_deeply_nested(self):
        base = {"a": {"b": {"c": {"d": 1}}}}
        override = {"a": {"b": {"c": {"e": 2}}}}
        result = deep_merge(base, override)
        self.assertEqual(result["a"]["b"]["c"]["d"], 1)
        self.assertEqual(result["a"]["b"]["c"]["e"], 2)

    def test_list_override(self):
        base = {"a": [1, 2, 3]}
        override = {"a": [4, 5]}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], [4, 5])

    def test_none_values(self):
        base = {"a": None}
        override = {"a": 1}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], 1)

    def test_multiple_keys(self):
        base = {"a": 1, "b": 2, "c": 3}
        override = {"b": 20, "d": 4}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": 1, "b": 20, "c": 3, "d": 4})


class TestConfigManagerImport(unittest.TestCase):
    def test_import_nonexistent_file(self):
        cm = ConfigManager()
        with self.assertRaises(FileNotFoundError):
            cm.import_all(Path("/nonexistent/config.yaml"))

    def test_import_oversized_file(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            big_file = Path(temp_dir) / "big.yaml"
            big_file.write_bytes(b"x: " + b"a" * (2 * 1024 * 1024))
            with self.assertRaises(ValueError):
                cm.import_all(big_file)

    def test_import_non_dict_yaml(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "list.yaml"
            yaml_file.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cm.import_all(yaml_file)

    def test_import_empty_yaml(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "empty.yaml"
            yaml_file.write_text("---\n", encoding="utf-8")
            result = cm.import_all(yaml_file)
            self.assertEqual(result, {})

    def test_import_filters_unknown_keys(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "extra.yaml"
            yaml_file.write_text(
                "general:\n  interval: 1.5\n  dangerous_key: hack\n",
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertIn("general", result)
            self.assertNotIn("dangerous_key", result["general"])

    def test_import_with_scripts(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "with_scripts.yaml"
            yaml_file.write_text(
                "general:\n  interval: 2.0\nscripts:\n  my_script:\n    enabled: true\n",
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertIn("general", result)
            self.assertIn("scripts", result)
            self.assertEqual(result["general"]["interval"], 2.0)

    def test_import_script_nonexistent_file(self):
        cm = ConfigManager()
        with self.assertRaises(FileNotFoundError):
            cm.import_script(Path("/nonexistent/script.yaml"))

    def test_import_script_oversized_file(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            big_file = Path(temp_dir) / "big.yaml"
            big_file.write_bytes(b"x: " + b"a" * (2 * 1024 * 1024))
            with self.assertRaises(ValueError):
                cm.import_script(big_file)

    def test_import_script_non_dict(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "list.yaml"
            yaml_file.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cm.import_script(yaml_file)

    def test_import_script_empty_file(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "empty.yaml"
            yaml_file.write_text("---\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cm.import_script(yaml_file)

    def test_import_script_valid(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "script.yaml"
            yaml_file.write_text(
                "__script_name__: my_script\nenabled: true\napi_key: secret\n",
                encoding="utf-8",
            )
            name, config = cm.import_script(yaml_file)
            self.assertEqual(name, "my_script")
            self.assertTrue(config["enabled"])

    def test_import_script_invalid_name(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "bad_name.yaml"
            yaml_file.write_text(
                "__script_name__: 'invalid-name!'\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                cm.import_script(yaml_file)


class TestConfigManagerExport(unittest.TestCase):
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


class TestSensitiveDataFilter(unittest.TestCase):
    def test_api_key_masked(self):
        f = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "api_key: sk-12345", (), None)
        f.filter(record)
        self.assertNotIn("sk-12345", record.msg)
        self.assertIn("***", record.msg)

    def test_token_masked(self):
        f = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "token: abc123", (), None)
        f.filter(record)
        self.assertNotIn("abc123", record.msg)

    def test_secret_masked(self):
        f = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "secret: mysecret", (), None)
        f.filter(record)
        self.assertNotIn("mysecret", record.msg)

    def test_password_masked(self):
        f = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "password: pass123", (), None)
        f.filter(record)
        self.assertNotIn("pass123", record.msg)

    def test_normal_message_unchanged(self):
        f = _SensitiveDataFilter()
        msg = "Normal log message"
        record = logging.LogRecord("test", logging.INFO, "", 0, msg, (), None)
        f.filter(record)
        self.assertEqual(record.msg, msg)

    def test_args_masked(self):
        f = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "Key: %s", ("api_key: secret123",), None)
        f.filter(record)
        if record.args:
            for arg in record.args:
                if isinstance(arg, str):
                    self.assertNotIn("secret123", arg)

    def test_case_insensitive(self):
        f = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "API_KEY: sk-12345", (), None)
        f.filter(record)
        self.assertNotIn("sk-12345", record.msg)

    def test_empty_message(self):
        f = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "", (), None)
        result = f.filter(record)
        self.assertTrue(result)

    def test_non_string_message(self):
        f = _SensitiveDataFilter()
        record = logging.LogRecord("test", logging.INFO, "", 0, 42, (), None)
        result = f.filter(record)
        self.assertTrue(result)


class TestClipboardModule(unittest.TestCase):
    def test_image_hash(self):
        from platex_client.clipboard import image_hash
        result = image_hash(b"test data")
        self.assertIsInstance(result, str)
        self.assertEqual(len(result), 64)

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

        def cb(is_publishing):
            called.append(is_publishing)

        set_publishing_callback(cb)
        set_publishing_callback(None)


if __name__ == "__main__":
    unittest.main()
