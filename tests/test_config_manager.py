from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from platex_client.config_manager import (
    ConfigManager,
    deep_merge,
    _apply_migrations,
)


class TestDeepMerge(unittest.TestCase):
    def test_simple_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": 1, "b": 3, "c": 4})

    def test_nested_merge(self):
        base = {"a": {"x": 1, "y": 2}}
        override = {"a": {"y": 3, "z": 4}}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": {"x": 1, "y": 3, "z": 4}})

    def test_deep_nested_merge(self):
        base = {"a": {"b": {"c": 1, "d": 2}}}
        override = {"a": {"b": {"d": 3, "e": 4}}}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": {"b": {"c": 1, "d": 3, "e": 4}}})

    def test_does_not_modify_original(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        result = deep_merge(base, override)
        self.assertNotIn("y", base["a"])

    def test_override_non_dict_with_dict(self):
        base = {"a": 1}
        override = {"a": {"x": 1}}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": {"x": 1}})

    def test_override_dict_with_non_dict(self):
        base = {"a": {"x": 1}}
        override = {"a": 1}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": 1})

    def test_empty_base(self):
        result = deep_merge({}, {"a": 1})
        self.assertEqual(result, {"a": 1})

    def test_empty_override(self):
        result = deep_merge({"a": 1}, {})
        self.assertEqual(result, {"a": 1})

    def test_both_empty(self):
        result = deep_merge({}, {})
        self.assertEqual(result, {})


class TestApplyMigrations(unittest.TestCase):
    def test_migration_from_v1_to_v2(self):
        payload = {"interval": 1.0}
        result = _apply_migrations(payload, 1, 2)
        self.assertIn("ui_language", result)
        self.assertIn("language_pack", result)
        self.assertIn("auto_start", result)
        self.assertIn("scripts", result)

    def test_migration_no_change_when_same_version(self):
        payload = {"interval": 1.0, "config_version": 2}
        result = _apply_migrations(payload, 2, 2)
        self.assertEqual(result, payload)

    def test_migration_adds_glm_vision_ocr_script(self):
        payload = {"glm_model": "test-model", "glm_base_url": "https://api.test.com"}
        result = _apply_migrations(payload, 1, 2)
        self.assertIn("glm_vision_ocr", result["scripts"])

    def test_migration_adds_hotkey_click_script(self):
        payload = {}
        result = _apply_migrations(payload, 1, 2)
        self.assertIn("hotkey_click", result["scripts"])

    def test_migration_preserves_existing_scripts(self):
        payload = {"scripts": {"glm_vision_ocr": {"model": "custom"}}}
        result = _apply_migrations(payload, 1, 2)
        self.assertEqual(result["scripts"]["glm_vision_ocr"]["model"], "custom")


class TestConfigManagerImportAll(unittest.TestCase):
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

    def test_import_with_scripts_section(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "with_scripts.yaml"
            yaml_file.write_text(
                "general:\n  interval: 1.5\nscripts:\n  my_script:\n    enabled: true\n",
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertIn("scripts", result)
            self.assertIn("my_script", result["scripts"])

    def test_import_symlink_rejected(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target.yaml"
            target.write_text("general:\n  interval: 1.5\n", encoding="utf-8")
            link = Path(temp_dir) / "link.yaml"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symlinks not supported on this platform")
            with self.assertRaises(ValueError):
                cm.import_all(link)


class TestConfigManagerImportScript(unittest.TestCase):
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

    def test_import_script_empty(self):
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
                "__script_name__: my_script\nthreshold: 0.8\n",
                encoding="utf-8",
            )
            name, config = cm.import_script(yaml_file)
            self.assertEqual(name, "my_script")
            self.assertEqual(config["threshold"], 0.8)

    def test_import_script_invalid_name(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "script.yaml"
            yaml_file.write_text(
                "__script_name__: 'invalid name!'\nthreshold: 0.8\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                cm.import_script(yaml_file)


class TestConfigManagerExportScript(unittest.TestCase):
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


class TestConfigManagerExportAll(unittest.TestCase):
    def test_export_all_creates_file(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "export.yaml"
            cm.export_all(export_path)
            self.assertTrue(export_path.exists())

    def test_export_all_with_registry(self):
        registry = MagicMock()
        registry.save_configs.return_value = {"my_script": {"enabled": True}}
        cm = ConfigManager(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "export.yaml"
            cm.export_all(export_path)
            self.assertTrue(export_path.exists())
            import yaml
            data = yaml.safe_load(export_path.read_text(encoding="utf-8"))
            self.assertIn("scripts", data)


if __name__ == "__main__":
    unittest.main()
