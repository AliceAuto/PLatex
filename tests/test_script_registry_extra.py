from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from platex_client.script_base import ScriptBase
from platex_client.script_registry import ScriptEntry, ScriptRegistry


class _TestScript(ScriptBase):
    @property
    def name(self):
        return "test"

    @property
    def display_name(self):
        return "Test"

    @property
    def description(self):
        return "Test script"


class _OcrScript(ScriptBase):
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


class _HotkeyScript(ScriptBase):
    @property
    def name(self):
        return "hotkey_test"

    @property
    def display_name(self):
        return "Hotkey Test"

    @property
    def description(self):
        return "Hotkey test script"

    def get_hotkey_bindings(self):
        return {"action1": "Ctrl+K"}


class TestScriptEntry(unittest.TestCase):
    def test_default_enabled(self):
        entry = ScriptEntry(script=_TestScript())
        self.assertTrue(entry.enabled)

    def test_custom_enabled(self):
        entry = ScriptEntry(script=_TestScript(), enabled=False)
        self.assertFalse(entry.enabled)

    def test_source_path_default_none(self):
        entry = ScriptEntry(script=_TestScript())
        self.assertIsNone(entry.source_path)

    def test_custom_source_path(self):
        entry = ScriptEntry(script=_TestScript(), source_path=Path("/test/script.py"))
        self.assertEqual(entry.source_path, Path("/test/script.py"))


class TestScriptRegistryGet(unittest.TestCase):
    def test_get_existing(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            entry = registry.get("test")
            self.assertIsNotNone(entry)

    def test_get_nonexistent(self):
        registry = ScriptRegistry()
        self.assertIsNone(registry.get("nonexistent"))


class TestScriptRegistryGetOcrScripts(unittest.TestCase):
    def test_ocr_scripts_found(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "ocr.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            ocr_scripts = registry.get_ocr_scripts()
            self.assertGreaterEqual(len(ocr_scripts), 1)

    def test_no_ocr_scripts(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "newstyle.py"
            script_path.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    name = 'my'\n"
                "    display_name = 'My'\n"
                "    description = 'My script'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            try:
                registry._load_script_file(script_path)
            except Exception:
                pass
            ocr_scripts = registry.get_ocr_scripts()
            self.assertEqual(len(ocr_scripts), 0)


class TestScriptRegistryGetHotkeyScripts(unittest.TestCase):
    def test_hotkey_scripts_empty(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "no_hotkey.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            hotkey_scripts = registry.get_hotkey_scripts()
            self.assertEqual(len(hotkey_scripts), 0)


class TestScriptRegistryGetEnabledScripts(unittest.TestCase):
    def test_all_enabled_by_default(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            enabled = registry.get_enabled_scripts()
            self.assertEqual(len(enabled), 1)

    def test_disabled_not_included(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            entry = registry._load_script_file(script_path)
            if entry:
                entry.enabled = False
            enabled = registry.get_enabled_scripts()
            self.assertEqual(len(enabled), 0)


class TestScriptRegistryGetAllScripts(unittest.TestCase):
    def test_includes_disabled(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            entry = registry._load_script_file(script_path)
            if entry:
                entry.enabled = False
            all_scripts = registry.get_all_scripts()
            self.assertEqual(len(all_scripts), 1)


class TestScriptRegistryClear(unittest.TestCase):
    def test_clear_removes_all(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            self.assertGreater(len(registry.entries), 0)
            registry.clear()
            self.assertEqual(len(registry.entries), 0)


class TestScriptRegistryLoadConfigs(unittest.TestCase):
    def test_load_configs_enables(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            registry.load_configs({"test": {"enabled": True}})
            entry = registry.get("test")
            self.assertTrue(entry.enabled)

    def test_load_configs_disables(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            registry.load_configs({"test": {"enabled": False}})
            entry = registry.get("test")
            self.assertFalse(entry.enabled)

    def test_load_configs_invalid_type(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            registry.load_configs({"test": "not_a_dict"})


class TestScriptRegistrySaveConfigs(unittest.TestCase):
    def test_save_configs(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            configs = registry.save_configs()
            self.assertIn("test", configs)
            self.assertIn("enabled", configs["test"])


class TestScriptRegistryDiscoverScripts(unittest.TestCase):
    def test_discover_from_empty_dir(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            registry.discover_scripts(Path(temp_dir))
            self.assertEqual(len(registry.entries), 0)

    def test_discover_skips_underscore_files(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            init_file = Path(temp_dir) / "__init__.py"
            init_file.write_text("x = 1\n", encoding="utf-8")
            registry.discover_scripts(Path(temp_dir))
            self.assertEqual(len(registry.entries), 0)

    def test_discover_from_nonexistent_dir(self):
        registry = ScriptRegistry()
        registry.discover_scripts(Path("/nonexistent/scripts"))


class TestScriptRegistryLoadScriptFile(unittest.TestCase):
    def test_load_nonexistent_returns_none(self):
        registry = ScriptRegistry()
        result = registry.load_script_file(Path("/nonexistent/script.py"))
        self.assertIsNone(result)

    def test_load_dangerous_returns_none(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "evil.py"
            script_path.write_text(
                "exec('print(1)')\ndef process_image(i,c): return 't'\n",
                encoding="utf-8",
            )
            result = registry.load_script_file(script_path)
            self.assertIsNone(result)

    def test_load_valid_script(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "good.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            result = registry.load_script_file(script_path)
            self.assertIsNotNone(result)
            self.assertTrue(result.enabled)

    def test_load_with_enabled_false(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "good.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            result = registry.load_script_file(script_path, enabled=False)
            self.assertIsNotNone(result)
            self.assertFalse(result.enabled)


class TestScriptRegistryEntries(unittest.TestCase):
    def test_entries_returns_copy(self):
        registry = ScriptRegistry()
        entries1 = registry.entries
        entries2 = registry.entries
        self.assertIsNot(entries1, entries2)


if __name__ == "__main__":
    unittest.main()
