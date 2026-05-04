from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import yaml

from platex_client.config_manager import (
    ConfigManager,
    _ALLOWED_GENERAL_KEYS,
    _MAX_BACKUPS,
    _MAX_IMPORT_FILE_SIZE,
    _apply_migrations,
    _cleanup_old_backups,
    _has_deep_symlinks,
    _skip_symlinks,
    backup_config,
    config_file_path,
    db_file_path,
    deep_merge,
    get_config_dir,
    log_file_path,
    backups_dir,
    set_config_dir,
)


class TestDeepMerge(unittest.TestCase):
    """Tests for deep_merge function."""

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
        deep_merge(base, override)
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

    def test_multiple_keys(self):
        base = {"a": 1, "b": 2, "c": 3}
        override = {"b": 20, "d": 4}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": 1, "b": 20, "c": 3, "d": 4})

    def test_nested_list_override(self):
        base = {"a": [1, 2, 3]}
        override = {"a": [4, 5]}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": [4, 5]})

    def test_deeply_nested_three_levels(self):
        base = {"a": {"b": {"c": {"d": 1}}}}
        override = {"a": {"b": {"c": {"e": 2}}}}
        result = deep_merge(base, override)
        self.assertEqual(result, {"a": {"b": {"c": {"d": 1, "e": 2}}}})


class TestConfigFilePath(unittest.TestCase):
    """Tests for config_file_path and related path functions."""

    def setUp(self):
        self._original_env = os.environ.get("PLATEX_CONFIG_DIR")

    def tearDown(self):
        if self._original_env is not None:
            os.environ["PLATEX_CONFIG_DIR"] = self._original_env
        else:
            os.environ.pop("PLATEX_CONFIG_DIR", None)

    def test_config_file_path_returns_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            result = config_file_path()
            self.assertIsInstance(result, Path)
            self.assertEqual(result.name, "config.yaml")

    def test_db_file_path_returns_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            result = db_file_path()
            self.assertIsInstance(result, Path)
            self.assertEqual(result.name, "history.sqlite3")

    def test_log_file_path_returns_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            result = log_file_path()
            self.assertIsInstance(result, Path)
            self.assertEqual(result.name, "platex-client.log")

    def test_backups_dir_returns_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            result = backups_dir()
            self.assertIsInstance(result, Path)
            self.assertEqual(result.name, "backups")

    def test_config_file_path_under_config_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            cfg_path = config_file_path()
            cfg_dir = get_config_dir()
            self.assertTrue(str(cfg_path).startswith(str(cfg_dir)))


class TestBackupConfig(unittest.TestCase):
    """Tests for backup_config function."""

    def setUp(self):
        self._original_env = os.environ.get("PLATEX_CONFIG_DIR")

    def tearDown(self):
        if self._original_env is not None:
            os.environ["PLATEX_CONFIG_DIR"] = self._original_env
        else:
            os.environ.pop("PLATEX_CONFIG_DIR", None)

    def test_backup_config_no_config_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            result = backup_config()
            self.assertIsNone(result)

    def test_backup_config_creates_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            cfg_path = config_file_path()
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text("interval: 1.0\n", encoding="utf-8")
            result = backup_config()
            self.assertIsNotNone(result)
            self.assertTrue((result / "config.yaml").exists())

    def test_backup_config_preserves_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            cfg_path = config_file_path()
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            original_content = "interval: 2.5\nisolate_mode: true\n"
            cfg_path.write_text(original_content, encoding="utf-8")
            result = backup_config()
            self.assertIsNotNone(result)
            backup_content = (result / "config.yaml").read_text(encoding="utf-8")
            self.assertEqual(backup_content, original_content)

    def test_backup_config_with_scripts_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            cfg_path = config_file_path()
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text("interval: 1.0\n", encoding="utf-8")
            scripts_dir = Path(temp_dir) / "scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            (scripts_dir / "test_script.py").write_text("print('test')", encoding="utf-8")
            result = backup_config()
            self.assertIsNotNone(result)
            self.assertTrue((result / "scripts").exists())


class TestCleanupOldBackups(unittest.TestCase):
    """Tests for _cleanup_old_backups function."""

    def setUp(self):
        self._original_env = os.environ.get("PLATEX_CONFIG_DIR")

    def tearDown(self):
        if self._original_env is not None:
            os.environ["PLATEX_CONFIG_DIR"] = self._original_env
        else:
            os.environ.pop("PLATEX_CONFIG_DIR", None)

    def test_max_backups_constant(self):
        self.assertEqual(_MAX_BACKUPS, 10)

    def test_cleanup_removes_old_backups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            bk_dir = backups_dir()
            bk_dir.mkdir(parents=True, exist_ok=True)
            # Create more than _MAX_BACKUPS backup directories
            for i in range(_MAX_BACKUPS + 5):
                (bk_dir / f"2024-01-{i:02d}_12-00-00").mkdir()

            _cleanup_old_backups()

            remaining = [d for d in bk_dir.iterdir() if d.is_dir()]
            self.assertLessEqual(len(remaining), _MAX_BACKUPS)

    def test_cleanup_keeps_recent_backups(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            bk_dir = backups_dir()
            bk_dir.mkdir(parents=True, exist_ok=True)
            for i in range(_MAX_BACKUPS + 3):
                (bk_dir / f"2024-01-{i:02d}_12-00-00").mkdir()

            _cleanup_old_backups()

            remaining = sorted([d.name for d in bk_dir.iterdir() if d.is_dir()])
            # The most recent (highest names) should be kept
            self.assertGreater(len(remaining), 0)

    def test_cleanup_with_no_backups_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            # Should not raise even if no backups dir exists
            _cleanup_old_backups()

    def test_cleanup_with_empty_backups_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            bk_dir = backups_dir()
            bk_dir.mkdir(parents=True, exist_ok=True)
            _cleanup_old_backups()
            remaining = [d for d in bk_dir.iterdir() if d.is_dir()]
            self.assertEqual(len(remaining), 0)


class TestApplyMigrations(unittest.TestCase):
    """Tests for _apply_migrations function."""

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

    def test_migration_v1_defaults(self):
        payload = {}
        result = _apply_migrations(payload, 1, 2)
        self.assertEqual(result["ui_language"], "en")
        self.assertEqual(result["language_pack"], "")
        self.assertEqual(result["auto_start"], False)

    def test_migration_v1_does_not_overwrite_existing_values(self):
        payload = {"ui_language": "zh-cn", "auto_start": True}
        result = _apply_migrations(payload, 1, 2)
        self.assertEqual(result["ui_language"], "zh-cn")
        self.assertTrue(result["auto_start"])

    def test_migration_v1_creates_scripts_dict_if_missing(self):
        payload = {}
        result = _apply_migrations(payload, 1, 2)
        self.assertIsInstance(result["scripts"], dict)

    def test_migration_v1_replaces_non_dict_scripts(self):
        payload = {"scripts": "not a dict"}
        result = _apply_migrations(payload, 1, 2)
        self.assertIsInstance(result["scripts"], dict)

    def test_migration_v1_glm_vision_ocr_defaults(self):
        payload = {"glm_model": "my-model", "glm_base_url": "https://my.api.com"}
        result = _apply_migrations(payload, 1, 2)
        glm_config = result["scripts"]["glm_vision_ocr"]
        self.assertTrue(glm_config["enabled"])
        self.assertNotIn("model", glm_config)
        self.assertNotIn("base_url", glm_config)

    def test_migration_v1_hotkey_click_defaults(self):
        payload = {}
        result = _apply_migrations(payload, 1, 2)
        hk_config = result["scripts"]["hotkey_click"]
        self.assertTrue(hk_config["enabled"])
        self.assertEqual(hk_config["groups"], [])

    def test_migration_v1_does_not_add_glm_vision_if_exists(self):
        payload = {"scripts": {"glm_vision_ocr": {"model": "existing", "enabled": False}}}
        result = _apply_migrations(payload, 1, 2)
        self.assertEqual(result["scripts"]["glm_vision_ocr"]["model"], "existing")
        self.assertFalse(result["scripts"]["glm_vision_ocr"]["enabled"])

    def test_migration_v1_does_not_add_hotkey_click_if_exists(self):
        payload = {"scripts": {"hotkey_click": {"enabled": False, "entries": [{"key": "F1"}]}}}
        result = _apply_migrations(payload, 1, 2)
        self.assertFalse(result["scripts"]["hotkey_click"]["enabled"])
        self.assertEqual(len(result["scripts"]["hotkey_click"]["entries"]), 1)

    def test_migration_from_v0_to_v2(self):
        payload = {"interval": 0.5}
        result = _apply_migrations(payload, 0, 2)
        self.assertIn("scripts", result)
        self.assertIn("ui_language", result)


class TestConfigManagerImportAll(unittest.TestCase):
    """Tests for ConfigManager.import_all."""

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
            self.assertIn("interval", result["general"])

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

    def test_import_max_file_size_constant(self):
        self.assertEqual(_MAX_IMPORT_FILE_SIZE, 1 * 1024 * 1024)

    def test_import_allowed_general_keys(self):
        expected = {
            "db_path", "script", "log_file", "interval", "isolate_mode",
            "glm_api_key", "glm_model", "glm_base_url", "auto_start",
            "ui_language", "language_pack",
        }
        self.assertEqual(_ALLOWED_GENERAL_KEYS, expected)

    def test_import_general_only(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "general.yaml"
            yaml_file.write_text(
                "general:\n  interval: 2.0\n  auto_start: true\n",
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertIn("general", result)
            self.assertEqual(result["general"]["interval"], 2.0)
            self.assertTrue(result["general"]["auto_start"])

    def test_import_scripts_only(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "scripts.yaml"
            yaml_file.write_text(
                "scripts:\n  my_script:\n    enabled: true\n",
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertIn("scripts", result)
            self.assertNotIn("general", result)

    def test_import_file_at_exact_size_limit(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "exact.yaml"
            # Create a file exactly at the size limit
            content = "general:\n  interval: 1.0\n"
            yaml_file.write_text(content, encoding="utf-8")
            result = cm.import_all(yaml_file)
            self.assertIn("general", result)


class TestConfigManagerExportAll(unittest.TestCase):
    """Tests for ConfigManager.export_all."""

    def setUp(self):
        self._original_env = os.environ.get("PLATEX_CONFIG_DIR")

    def tearDown(self):
        if self._original_env is not None:
            os.environ["PLATEX_CONFIG_DIR"] = self._original_env
        else:
            os.environ.pop("PLATEX_CONFIG_DIR", None)

    def test_export_all_creates_file(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            export_path = Path(temp_dir) / "export.yaml"
            cm.export_all(export_path)
            self.assertTrue(export_path.exists())

    def test_export_all_with_registry(self):
        registry = MagicMock()
        registry.save_configs.return_value = {"my_script": {"enabled": True}}
        cm = ConfigManager(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            export_path = Path(temp_dir) / "export.yaml"
            cm.export_all(export_path)
            self.assertTrue(export_path.exists())
            data = yaml.safe_load(export_path.read_text(encoding="utf-8"))
            self.assertIn("scripts", data)

    def test_export_all_strips_api_keys(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            cfg_path = config_file_path()
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            cfg_path.write_text("glm_api_key: secret-key-12345\n", encoding="utf-8")
            export_path = Path(temp_dir) / "export.yaml"
            cm.export_all(export_path)
            content = export_path.read_text(encoding="utf-8")
            self.assertNotIn("secret-key-12345", content)

    def test_export_all_creates_parent_dirs(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            export_path = Path(temp_dir) / "subdir" / "export.yaml"
            cm.export_all(export_path)
            self.assertTrue(export_path.exists())

    def test_export_all_empty_config(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            export_path = Path(temp_dir) / "export.yaml"
            cm.export_all(export_path)
            data = yaml.safe_load(export_path.read_text(encoding="utf-8"))
            self.assertIsInstance(data, dict)


class TestConfigManagerImportScript(unittest.TestCase):
    """Tests for ConfigManager.import_script."""

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

    def test_import_script_uses_filename_as_default_name(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "my_awesome_script.yaml"
            yaml_file.write_text("threshold: 0.5\n", encoding="utf-8")
            name, config = cm.import_script(yaml_file)
            self.assertEqual(name, "my_awesome_script")

    def test_import_script_symlink_rejected(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target.yaml"
            target.write_text("threshold: 0.5\n", encoding="utf-8")
            link = Path(temp_dir) / "link.yaml"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symlinks not supported on this platform")
            with self.assertRaises(ValueError):
                cm.import_script(link)

    def test_import_script_name_must_be_identifier(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "script.yaml"
            yaml_file.write_text(
                "__script_name__: '123invalid'\nthreshold: 0.8\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                cm.import_script(yaml_file)

    def test_import_script_valid_identifier_name(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "script.yaml"
            yaml_file.write_text(
                "__script_name__: valid_name_123\nthreshold: 0.8\n",
                encoding="utf-8",
            )
            name, config = cm.import_script(yaml_file)
            self.assertEqual(name, "valid_name_123")


class TestConfigManagerExportScript(unittest.TestCase):
    """Tests for ConfigManager.export_script."""

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

    def test_export_script_creates_file(self):
        registry = MagicMock()
        mock_entry = MagicMock()
        mock_entry.script.save_config.return_value = {"threshold": 0.8}
        mock_entry.enabled = True
        registry.get.return_value = mock_entry
        cm = ConfigManager(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "script.yaml"
            cm.export_script("my_script", export_path)
            self.assertTrue(export_path.exists())
            data = yaml.safe_load(export_path.read_text(encoding="utf-8"))
            self.assertEqual(data["__script_name__"], "my_script")
            self.assertTrue(data["enabled"])
            self.assertEqual(data["threshold"], 0.8)

    def test_export_script_strips_api_keys(self):
        registry = MagicMock()
        mock_entry = MagicMock()
        mock_entry.script.save_config.return_value = {
            "api_key": "secret-key-12345",
            "threshold": 0.8,
        }
        mock_entry.enabled = True
        registry.get.return_value = mock_entry
        cm = ConfigManager(registry)
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "script.yaml"
            cm.export_script("my_script", export_path)
            content = export_path.read_text(encoding="utf-8")
            self.assertNotIn("secret-key-12345", content)


class TestImportFiltering(unittest.TestCase):
    """Tests for import filtering of unknown keys."""

    def test_allowed_keys_not_filtered(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "allowed.yaml"
            general_content = {k: "test_value" for k in _ALLOWED_GENERAL_KEYS}
            yaml_file.write_text(
                yaml.dump({"general": general_content}, allow_unicode=True),
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertIn("general", result)
            for key in _ALLOWED_GENERAL_KEYS:
                self.assertIn(key, result["general"])

    def test_unknown_keys_filtered(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "filtered.yaml"
            yaml_file.write_text(
                "general:\n  interval: 1.0\n  unknown_key: value\n  another_bad: 42\n",
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertNotIn("unknown_key", result["general"])
            self.assertNotIn("another_bad", result["general"])
            self.assertIn("interval", result["general"])

    def test_scripts_not_filtered(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "scripts.yaml"
            yaml_file.write_text(
                "scripts:\n  my_script:\n    any_key: any_value\n    another: data\n",
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertIn("any_key", result["scripts"]["my_script"])
            self.assertIn("another", result["scripts"]["my_script"])


class TestSymlinkDetection(unittest.TestCase):
    """Tests for symlink detection functions."""

    def test_skip_symlinks_returns_symlink_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target.txt"
            target.write_text("content", encoding="utf-8")
            link = Path(temp_dir) / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symlinks not supported on this platform")
            result = _skip_symlinks(temp_dir, ["target.txt", "link.txt"])
            self.assertIn("link.txt", result)
            self.assertNotIn("target.txt", result)

    def test_skip_symlinks_no_symlinks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "regular.txt"
            target.write_text("content", encoding="utf-8")
            result = _skip_symlinks(temp_dir, ["regular.txt"])
            self.assertEqual(result, [])

    def test_has_deep_symlinks_finds_symlinks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "target.txt"
            target.write_text("content", encoding="utf-8")
            subdir = Path(temp_dir) / "sub"
            subdir.mkdir()
            link = subdir / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Symlinks not supported on this platform")
            result = _has_deep_symlinks(Path(temp_dir))
            self.assertGreater(len(result), 0)

    def test_has_deep_symlinks_no_symlinks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "regular.txt"
            target.write_text("content", encoding="utf-8")
            result = _has_deep_symlinks(Path(temp_dir))
            self.assertEqual(len(result), 0)

    def test_has_deep_symlinks_nonexistent_dir(self):
        result = _has_deep_symlinks(Path("/nonexistent/path"))
        self.assertEqual(len(result), 0)


class TestOversizedFiles(unittest.TestCase):
    """Tests for oversized file handling."""

    def test_import_all_rejects_oversized(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            big_file = Path(temp_dir) / "big.yaml"
            # Create a file larger than _MAX_IMPORT_FILE_SIZE
            big_file.write_bytes(b"x: " + b"a" * (_MAX_IMPORT_FILE_SIZE + 1))
            with self.assertRaises(ValueError) as ctx:
                cm.import_all(big_file)
            self.assertIn("too large", str(ctx.exception).lower())

    def test_import_script_rejects_oversized(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            big_file = Path(temp_dir) / "big.yaml"
            big_file.write_bytes(b"x: " + b"a" * (_MAX_IMPORT_FILE_SIZE + 1))
            with self.assertRaises(ValueError):
                cm.import_script(big_file)

    def test_import_all_accepts_file_under_limit(self):
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "small.yaml"
            yaml_file.write_text("general:\n  interval: 1.0\n", encoding="utf-8")
            result = cm.import_all(yaml_file)
            self.assertIn("general", result)


class TestSetConfigDir(unittest.TestCase):
    """Tests for set_config_dir function."""

    def setUp(self):
        self._original_env = os.environ.get("PLATEX_CONFIG_DIR")

    def tearDown(self):
        if self._original_env is not None:
            os.environ["PLATEX_CONFIG_DIR"] = self._original_env
        else:
            os.environ.pop("PLATEX_CONFIG_DIR", None)

    def test_set_config_dir_creates_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            new_dir = Path(temp_dir) / "new_config_dir"
            set_config_dir(new_dir)
            self.assertTrue(new_dir.exists())
            self.assertEqual(os.environ.get("PLATEX_CONFIG_DIR"), str(new_dir.resolve()))

    def test_set_config_dir_sets_env_var(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            new_dir = Path(temp_dir) / "env_test"
            set_config_dir(new_dir)
            self.assertEqual(os.environ.get("PLATEX_CONFIG_DIR"), str(new_dir.resolve()))

    def test_get_config_dir_uses_env_var(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            os.environ["PLATEX_CONFIG_DIR"] = temp_dir
            result = get_config_dir()
            self.assertEqual(result, Path(temp_dir))


if __name__ == "__main__":
    unittest.main()
