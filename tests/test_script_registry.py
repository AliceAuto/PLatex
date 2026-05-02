from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from platex_client.script_base import ScriptBase
from platex_client.script_registry import ScriptEntry, ScriptRegistry


class _FakeScript(ScriptBase):
    def __init__(self, name, display_name="Fake", description="Fake script", has_ocr=False):
        self._name = name
        self._display_name = display_name
        self._description = description
        self._has_ocr = has_ocr

    @property
    def name(self):
        return self._name

    @property
    def display_name(self):
        return self._display_name

    @property
    def description(self):
        return self._description

    def has_ocr_capability(self):
        return self._has_ocr


class TestScriptRegistryInit(unittest.TestCase):
    def test_empty_registry(self):
        registry = ScriptRegistry()
        self.assertEqual(len(registry.entries), 0)


class TestScriptRegistryGet(unittest.TestCase):
    def test_get_nonexistent_returns_none(self):
        registry = ScriptRegistry()
        result = registry.get("nonexistent")
        self.assertIsNone(result)

    def test_get_existing_entry(self):
        registry = ScriptRegistry()
        script = _FakeScript("test")
        registry._entries["test"] = ScriptEntry(script=script)
        result = registry.get("test")
        self.assertIsNotNone(result)
        self.assertIs(result.script, script)


class TestScriptRegistryGetOcrScripts(unittest.TestCase):
    def test_no_ocr_scripts(self):
        registry = ScriptRegistry()
        script = _FakeScript("test", has_ocr=False)
        registry._entries["test"] = ScriptEntry(script=script)
        result = registry.get_ocr_scripts()
        self.assertEqual(len(result), 0)

    def test_with_ocr_scripts(self):
        registry = ScriptRegistry()
        ocr_script = _FakeScript("ocr_test", has_ocr=True)
        non_ocr_script = _FakeScript("non_ocr", has_ocr=False)
        registry._entries["ocr_test"] = ScriptEntry(script=ocr_script)
        registry._entries["non_ocr"] = ScriptEntry(script=non_ocr_script)
        result = registry.get_ocr_scripts()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].script.name, "ocr_test")

    def test_disabled_ocr_scripts_excluded(self):
        registry = ScriptRegistry()
        ocr_script = _FakeScript("ocr_test", has_ocr=True)
        registry._entries["ocr_test"] = ScriptEntry(script=ocr_script, enabled=False)
        result = registry.get_ocr_scripts()
        self.assertEqual(len(result), 0)


class TestScriptRegistryGetHotkeyScripts(unittest.TestCase):
    def test_no_hotkey_scripts(self):
        registry = ScriptRegistry()
        script = _FakeScript("test")
        registry._entries["test"] = ScriptEntry(script=script)
        result = registry.get_hotkey_scripts()
        self.assertEqual(len(result), 0)


class TestScriptRegistryGetEnabledScripts(unittest.TestCase):
    def test_all_enabled(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        s2 = _FakeScript("s2")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=True)
        registry._entries["s2"] = ScriptEntry(script=s2, enabled=True)
        result = registry.get_enabled_scripts()
        self.assertEqual(len(result), 2)

    def test_mixed_enabled(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        s2 = _FakeScript("s2")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=True)
        registry._entries["s2"] = ScriptEntry(script=s2, enabled=False)
        result = registry.get_enabled_scripts()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].script.name, "s1")

    def test_all_disabled(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=False)
        result = registry.get_enabled_scripts()
        self.assertEqual(len(result), 0)


class TestScriptRegistryGetAllScripts(unittest.TestCase):
    def test_empty(self):
        registry = ScriptRegistry()
        result = registry.get_all_scripts()
        self.assertEqual(len(result), 0)

    def test_with_scripts(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        s2 = _FakeScript("s2")
        registry._entries["s1"] = ScriptEntry(script=s1)
        registry._entries["s2"] = ScriptEntry(script=s2)
        result = registry.get_all_scripts()
        self.assertEqual(len(result), 2)


class TestScriptRegistryClear(unittest.TestCase):
    def test_clear(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1)
        registry.clear()
        self.assertEqual(len(registry.entries), 0)

    def test_clear_empty(self):
        registry = ScriptRegistry()
        registry.clear()
        self.assertEqual(len(registry.entries), 0)


class TestScriptRegistryEntries(unittest.TestCase):
    def test_entries_returns_copy(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1)
        entries = registry.entries
        entries["s2"] = ScriptEntry(script=_FakeScript("s2"))
        self.assertNotIn("s2", registry._entries)


class TestScriptRegistryDiscoverScripts(unittest.TestCase):
    def test_discover_nonexistent_dir(self):
        registry = ScriptRegistry()
        registry.discover_scripts(Path("/nonexistent/scripts"))
        self.assertEqual(len(registry.entries), 0)

    def test_discover_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ScriptRegistry()
            registry.discover_scripts(Path(tmpdir))
            self.assertEqual(len(registry.entries), 0)

    def test_discover_skips_underscore_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            init_file = Path(tmpdir) / "__init__.py"
            init_file.write_text("# init", encoding="utf-8")
            registry = ScriptRegistry()
            registry.discover_scripts(Path(tmpdir))
            self.assertEqual(len(registry.entries), 0)


class TestScriptRegistryLoadConfigs(unittest.TestCase):
    def test_load_configs(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=True)
        configs = {"s1": {"enabled": False}}
        registry.load_configs(configs)
        self.assertFalse(registry._entries["s1"].enabled)

    def test_load_configs_missing_script(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=True)
        configs = {"nonexistent": {"enabled": False}}
        registry.load_configs(configs)
        self.assertTrue(registry._entries["s1"].enabled)

    def test_load_configs_invalid_config(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=True)
        configs = {"s1": "not_a_dict"}
        registry.load_configs(configs)
        self.assertTrue(registry._entries["s1"].enabled)


class TestScriptRegistrySaveConfigs(unittest.TestCase):
    def test_save_configs(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=True)
        configs = registry.save_configs()
        self.assertIn("s1", configs)
        self.assertTrue(configs["s1"]["enabled"])

    def test_save_configs_disabled(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=False)
        configs = registry.save_configs()
        self.assertFalse(configs["s1"]["enabled"])


class TestScriptEntry(unittest.TestCase):
    def test_default_enabled(self):
        script = _FakeScript("test")
        entry = ScriptEntry(script=script)
        self.assertTrue(entry.enabled)

    def test_default_source_path_none(self):
        script = _FakeScript("test")
        entry = ScriptEntry(script=script)
        self.assertIsNone(entry.source_path)

    def test_custom_values(self):
        script = _FakeScript("test")
        path = Path("/some/path")
        entry = ScriptEntry(script=script, enabled=False, source_path=path)
        self.assertFalse(entry.enabled)
        self.assertEqual(entry.source_path, path)


if __name__ == "__main__":
    unittest.main()
