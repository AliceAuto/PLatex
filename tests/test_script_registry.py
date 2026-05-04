from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platex_client.script_base import ScriptBase
from platex_client.script_registry import (
    ScriptEntry,
    ScriptRegistry,
    _LegacyOcrAdapter,
    default_scripts_dir,
)
from platex_client.script_safety import _SCRIPT_SAFETY_ENV


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeScript(ScriptBase):
    """Concrete ScriptBase for testing."""

    def __init__(
        self,
        name="fake",
        display_name="Fake",
        description="Fake script",
        has_ocr=False,
        hotkey_bindings=None,
    ):
        self._name = name
        self._display_name = display_name
        self._description = description
        self._has_ocr = has_ocr
        self._hotkey_bindings = hotkey_bindings or {}
        self._loaded_config = None

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

    def get_hotkey_bindings(self):
        return self._hotkey_bindings

    def load_config(self, config):
        self._loaded_config = config

    def save_config(self):
        return self._loaded_config if self._loaded_config is not None else {}


# ---------------------------------------------------------------------------
# ScriptEntry tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# ScriptRegistry init and entries
# ---------------------------------------------------------------------------


class TestScriptRegistryInit(unittest.TestCase):
    def test_empty_registry(self):
        registry = ScriptRegistry()
        self.assertEqual(len(registry.entries), 0)

    def test_entries_returns_copy(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1)
        entries = registry.entries
        entries["s2"] = ScriptEntry(script=_FakeScript("s2"))
        self.assertNotIn("s2", registry._entries)


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# get_ocr_scripts()
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# get_hotkey_scripts()
# ---------------------------------------------------------------------------


class TestScriptRegistryGetHotkeyScripts(unittest.TestCase):
    def test_no_hotkey_scripts(self):
        registry = ScriptRegistry()
        script = _FakeScript("test")
        registry._entries["test"] = ScriptEntry(script=script)
        result = registry.get_hotkey_scripts()
        self.assertEqual(len(result), 0)

    def test_with_hotkey_scripts(self):
        registry = ScriptRegistry()
        hk_script = _FakeScript("hk_test", hotkey_bindings={"ocr": "Ctrl+Shift+O"})
        no_hk_script = _FakeScript("no_hk")
        registry._entries["hk_test"] = ScriptEntry(script=hk_script)
        registry._entries["no_hk"] = ScriptEntry(script=no_hk_script)
        result = registry.get_hotkey_scripts()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].script.name, "hk_test")

    def test_disabled_hotkey_scripts_excluded(self):
        registry = ScriptRegistry()
        hk_script = _FakeScript("hk_test", hotkey_bindings={"ocr": "Ctrl+Shift+O"})
        registry._entries["hk_test"] = ScriptEntry(script=hk_script, enabled=False)
        result = registry.get_hotkey_scripts()
        self.assertEqual(len(result), 0)


# ---------------------------------------------------------------------------
# get_enabled_scripts()
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# get_all_scripts()
# ---------------------------------------------------------------------------


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

    def test_includes_disabled(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=False)
        result = registry.get_all_scripts()
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# discover_scripts()
# ---------------------------------------------------------------------------


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

    def test_discover_loads_py_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ocr_test.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            registry.discover_scripts(Path(tmpdir))
            self.assertEqual(len(registry.entries), 1)
            self.assertIn("ocr_test", registry.entries)

    def test_discover_skips_non_py_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            txt_file = Path(tmpdir) / "readme.txt"
            txt_file.write_text("not a script", encoding="utf-8")
            registry = ScriptRegistry()
            registry.discover_scripts(Path(tmpdir))
            self.assertEqual(len(registry.entries), 0)

    def test_discover_multiple_scripts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ("alpha.py", "beta.py", "gamma.py"):
                Path(tmpdir, name).write_text(
                    f"def process_image(image_bytes, context=None):\n    return '{name}'\n",
                    encoding="utf-8",
                )
            registry = ScriptRegistry()
            registry.discover_scripts(Path(tmpdir))
            self.assertEqual(len(registry.entries), 3)

    def test_discover_sets_scripts_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ScriptRegistry()
            registry.discover_scripts(Path(tmpdir))
            self.assertEqual(registry._scripts_dir, Path(tmpdir))

    def test_discover_adds_to_allowed_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ScriptRegistry()
            registry.discover_scripts(Path(tmpdir))
            resolved = Path(tmpdir).resolve()
            self.assertIn(resolved, registry._allowed_dirs)

    def test_discover_handles_bad_script_gracefully(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_script = Path(tmpdir) / "bad.py"
            bad_script.write_text("this is not valid python {{{", encoding="utf-8")
            good_script = Path(tmpdir) / "good.py"
            good_script.write_text(
                "def process_image(image_bytes, context=None):\n    return 'ok'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            registry.discover_scripts(Path(tmpdir))
            # Bad script should be skipped, good one should load
            self.assertEqual(len(registry.entries), 1)
            self.assertIn("good", registry.entries)


# ---------------------------------------------------------------------------
# load_script_file()
# ---------------------------------------------------------------------------


class TestScriptRegistryLoadScriptFile(unittest.TestCase):
    def test_load_new_style_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "new_style.py"
            script_path.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'my_script'\n"
                "    @property\n"
                "    def display_name(self): return 'My Script'\n"
                "    @property\n"
                "    def description(self): return 'Test'\n"
                "    def has_ocr_capability(self): return True\n"
                "    def process_image(self, image_bytes, context=None): return 'result'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.script.name, "my_script")
            self.assertTrue(entry.enabled)

    def test_load_legacy_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "legacy.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.script.name, "legacy")

    def test_load_script_with_enabled_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "disabled.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path, enabled=False)
            self.assertIsNotNone(entry)
            self.assertFalse(entry.enabled)

    def test_load_script_no_entry_point_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "no_entry.py"
            script_path.write_text("x = 42\n", encoding="utf-8")
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertIsNone(entry)

    def test_load_script_bad_syntax_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "bad.py"
            script_path.write_text("def foo(\n", encoding="utf-8")
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertIsNone(entry)

    def test_load_script_file_sets_source_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "sourced.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.source_path, script_path)


# ---------------------------------------------------------------------------
# duplicate names
# ---------------------------------------------------------------------------


class TestScriptRegistryDuplicateNames(unittest.TestCase):
    def test_duplicate_name_different_path_skipped(self):
        """Two scripts with the same name from different paths: second is skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = Path(tmpdir) / "script_a.py"
            path1.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'duplicate'\n"
                "    @property\n"
                "    def display_name(self): return 'First'\n"
                "    @property\n"
                "    def description(self): return 'First script'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            path2 = Path(tmpdir) / "script_b.py"
            path2.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'duplicate'\n"
                "    @property\n"
                "    def display_name(self): return 'Second'\n"
                "    @property\n"
                "    def description(self): return 'Second script'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry1 = registry.load_script_file(path1)
            self.assertIsNotNone(entry1)
            entry2 = registry.load_script_file(path2)
            self.assertIsNone(entry2)
            # Original should still be there
            self.assertEqual(registry.get("duplicate").script.display_name, "First")

    def test_duplicate_name_same_path_reloads(self):
        """Same script name from the same path: reloads."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "reloadable.py"
            path.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'reloadable'\n"
                "    @property\n"
                "    def display_name(self): return 'Version 1'\n"
                "    @property\n"
                "    def description(self): return 'First version'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry1 = registry.load_script_file(path)
            self.assertIsNotNone(entry1)
            self.assertEqual(entry1.script.display_name, "Version 1")

            # Reload from same path
            entry2 = registry.load_script_file(path)
            self.assertIsNotNone(entry2)
            # Should be reloaded (same path resolves to same location)
            self.assertEqual(len(registry.entries), 1)


# ---------------------------------------------------------------------------
# dangerous code blocking
# ---------------------------------------------------------------------------


class TestScriptRegistryDangerousCodeBlocking(unittest.TestCase):
    def test_blocked_pattern_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "evil.py"
            script_path.write_text(
                "import os\n"
                "os.system('rm -rf /')\n"
                "def process_image(image_bytes, context=None): return 'x'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            # _load_script_file raises ValueError; load_script_file catches and returns None
            entry = registry.load_script_file(script_path)
            self.assertIsNone(entry)

    def test_dangerous_pattern_blocked_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dangerous.py"
            script_path.write_text(
                "import shutil\n"
                "shutil.copy('a', 'b')\n"
                "def process_image(image_bytes, context=None): return 'x'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertIsNone(entry)

    def test_dangerous_pattern_allowed_with_env_var(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dangerous_allowed.py"
            script_path.write_text(
                "import shutil\n"
                "def _unsafe(): shutil.copy('a', 'b')\n"
                "def process_image(image_bytes, context=None): return 'x'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            with patch.dict(os.environ, {_SCRIPT_SAFETY_ENV: "1"}):
                entry = registry.load_script_file(script_path)
                self.assertIsNotNone(entry)

    def test_blocked_pattern_not_allowed_even_with_env_var(self):
        """Blocked patterns (like os.system) cannot be bypassed with env var in registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "blocked.py"
            script_path.write_text(
                "import os\n"
                "os.system('echo hello')\n"
                "def process_image(image_bytes, context=None): return 'x'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            with patch.dict(os.environ, {_SCRIPT_SAFETY_ENV: "1"}):
                entry = registry.load_script_file(script_path)
                # Blocked patterns cannot be bypassed
                self.assertIsNone(entry)


# ---------------------------------------------------------------------------
# _LegacyOcrAdapter
# ---------------------------------------------------------------------------


class TestLegacyOcrAdapter(unittest.TestCase):
    def test_name_from_source_path_stem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "my_ocr_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.script.name, "my_ocr_script")

    def test_display_name_from_source_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "my_ocr_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertEqual(entry.script.display_name, "My Ocr Script")

    def test_description_from_module_docstring(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "doc_script.py"
            script_path.write_text(
                '"""This is the docstring."""\n'
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertEqual(entry.script.description, "This is the docstring.")

    def test_description_fallback_without_docstring(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "no_doc.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertIn("no_doc", entry.script.description)

    def test_has_ocr_capability_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ocr.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            self.assertTrue(entry.script.has_ocr_capability())

    def test_process_image_delegates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ocr.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2 + y^2'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            result = entry.script.process_image(b"img")
            self.assertEqual(result, "x^2 + y^2")

    def test_process_image_dict_return(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dict_ocr.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n"
                "    return {'latex': 'a^2'}\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            result = entry.script.process_image(b"img")
            self.assertEqual(result, "a^2")

    def test_process_image_empty_result_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "empty_ocr.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return ''\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            with self.assertRaises(RuntimeError):
                entry.script.process_image(b"img")

    def test_process_image_missing_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "missing_pi.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'ok'\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry.load_script_file(script_path)
            # Remove process_image from the module
            del entry.script._module.process_image
            with self.assertRaises(RuntimeError):
                entry.script.process_image(b"img")


# ---------------------------------------------------------------------------
# load_configs()
# ---------------------------------------------------------------------------


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
        # Invalid config should default to enabled=True
        self.assertTrue(registry._entries["s1"].enabled)

    def test_load_configs_passes_config_to_script(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1)
        configs = {"s1": {"enabled": True, "key": "value"}}
        registry.load_configs(configs)
        self.assertEqual(s1._loaded_config, {"enabled": True, "key": "value"})

    def test_load_configs_empty_configs(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=False)
        registry.load_configs({})
        # No config for s1, so enabled defaults to True
        self.assertTrue(registry._entries["s1"].enabled)


# ---------------------------------------------------------------------------
# save_configs()
# ---------------------------------------------------------------------------


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

    def test_save_configs_includes_script_config(self):
        registry = ScriptRegistry()
        s1 = _FakeScript("s1")
        s1._loaded_config = {"api_key": "test"}
        registry._entries["s1"] = ScriptEntry(script=s1, enabled=True)
        configs = registry.save_configs()
        self.assertEqual(configs["s1"]["api_key"], "test")
        self.assertTrue(configs["s1"]["enabled"])

    def test_save_configs_handles_non_dict_return(self):
        """If save_config returns non-dict, it should be replaced with empty dict."""

        class _BadSaveScript(ScriptBase):
            @property
            def name(self): return "bad_save"
            @property
            def display_name(self): return "Bad Save"
            @property
            def description(self): return "Bad save"
            def save_config(self): return "not a dict"

        registry = ScriptRegistry()
        s1 = _BadSaveScript()
        registry._entries["bad_save"] = ScriptEntry(script=s1, enabled=True)
        configs = registry.save_configs()
        self.assertIn("bad_save", configs)
        self.assertTrue(configs["bad_save"]["enabled"])

    def test_save_configs_empty_registry(self):
        registry = ScriptRegistry()
        configs = registry.save_configs()
        self.assertEqual(configs, {})


# ---------------------------------------------------------------------------
# default_scripts_dir()
# ---------------------------------------------------------------------------


class TestDefaultScriptsDir(unittest.TestCase):
    def test_returns_path(self):
        result = default_scripts_dir()
        self.assertIsInstance(result, Path)

    def test_returns_existing_or_candidate(self):
        result = default_scripts_dir()
        # It should return a Path object; may or may not exist
        self.assertIsInstance(result, Path)


if __name__ == "__main__":
    unittest.main()
