from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from platex_client.script_base import ScriptBase, TrayMenuItem
from platex_client.script_context import (
    ClipboardAPI,
    ConfigAPI,
    HistoryAPI,
    HotkeyAPI,
    LoggerAPI,
    MouseAPI,
    NotificationAPI,
    SchedulerAPI,
    ScriptContext,
    WindowAPI,
)
from platex_client.script_registry import ScriptRegistry, ScriptEntry
from platex_client.script_safety import (
    _check_dangerous_patterns,
    _extract_legacy_result,
    _load_script_module,
    scan_script_source,
    check_blocked_patterns,
    validate_script_path,
)
from platex_client.models import ClipboardEvent


class ConcreteScript(ScriptBase):
    @property
    def name(self):
        return "test_script"

    @property
    def display_name(self):
        return "Test Script"

    @property
    def description(self):
        return "A test script"


class OcrScript(ScriptBase):
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
        return r"\alpha + \beta"


class HotkeyScript(ScriptBase):
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
        return {"action1": "Ctrl+Alt+1"}

    def on_hotkey(self, action):
        pass


class TestScriptBaseInit(unittest.TestCase):
    def test_context_initially_none(self):
        script = ConcreteScript()
        self.assertIsNone(script.context)

    def test_on_context_ready_sets_context(self):
        script = ConcreteScript()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        self.assertIs(script.context, ctx)

    def test_tray_action_callback_initially_none(self):
        script = ConcreteScript()
        self.assertIsNone(script._tray_action_callback)

    def test_set_tray_action_callback(self):
        script = ConcreteScript()
        cb = lambda a, p: None
        script.set_tray_action_callback(cb)
        self.assertIs(script._tray_action_callback, cb)

    def test_hotkeys_changed_callback_initially_none(self):
        script = ConcreteScript()
        self.assertIsNone(script._hotkeys_changed_callback)


class TestScriptBaseActivateDeactivate(unittest.TestCase):
    def test_activate_noop(self):
        script = ConcreteScript()
        script.activate()

    def test_deactivate_clears_context(self):
        script = ConcreteScript()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        script.deactivate()
        self.assertIsNone(script.context)

    def test_deactivate_calls_context_shutdown(self):
        script = ConcreteScript()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        script.deactivate()
        ctx.shutdown.assert_called_once()

    def test_deactivate_no_context_no_error(self):
        script = ConcreteScript()
        script.deactivate()


class TestScriptBaseOcrCapability(unittest.TestCase):
    def test_default_no_ocr(self):
        script = ConcreteScript()
        self.assertFalse(script.has_ocr_capability())

    def test_process_image_without_ocr_raises(self):
        script = ConcreteScript()
        with self.assertRaises(RuntimeError):
            script.process_image(b"fake", {})

    def test_ocr_script_process_image(self):
        script = OcrScript()
        self.assertTrue(script.has_ocr_capability())
        result = script.process_image(b"fake", {})
        self.assertEqual(result, r"\alpha + \beta")


class TestScriptBaseHotkeys(unittest.TestCase):
    def test_default_no_hotkeys(self):
        script = ConcreteScript()
        self.assertEqual(script.get_hotkey_bindings(), {})

    def test_hotkey_script_bindings(self):
        script = HotkeyScript()
        bindings = script.get_hotkey_bindings()
        self.assertIn("action1", bindings)
        self.assertEqual(bindings["action1"], "Ctrl+Alt+1")

    def test_on_hotkey_noop(self):
        script = ConcreteScript()
        script.on_hotkey("test")

    def test_passthrough_hotkeys_default_false(self):
        script = ConcreteScript()
        self.assertFalse(script.passthrough_hotkeys)


class TestScriptBaseConfig(unittest.TestCase):
    def test_load_config_noop(self):
        script = ConcreteScript()
        script.load_config({"key": "value"})

    def test_save_config_returns_empty(self):
        script = ConcreteScript()
        self.assertEqual(script.save_config(), {})


class TestScriptBaseTrayMenu(unittest.TestCase):
    def test_default_tray_menu_empty(self):
        script = ConcreteScript()
        self.assertEqual(script.get_tray_menu_items(), [])

    def test_set_tray_action_callback_and_invoke(self):
        script = ConcreteScript()
        called_with = []
        script.set_tray_action_callback(lambda a, p: called_with.append((a, p)))
        script._tray_action_callback("action", "param")
        self.assertEqual(called_with, [("action", "param")])


class TestScriptBaseTestConnection(unittest.TestCase):
    def test_default_test_connection(self):
        script = ConcreteScript()
        success, msg = script.test_connection()
        self.assertTrue(success)
        self.assertEqual(msg, "OK")


class TestScriptBaseImportExportConfig(unittest.TestCase):
    def test_import_config_valid(self):
        script = ConcreteScript()
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("key: value\n", encoding="utf-8")
            result = script.import_config(config_path)
            self.assertEqual(result, {"key": "value"})

    def test_import_config_path_traversal_rejected(self):
        script = ConcreteScript()
        with self.assertRaises(ValueError):
            script.import_config("../../etc/config.yaml")

    def test_import_config_nonexistent(self):
        script = ConcreteScript()
        with self.assertRaises(FileNotFoundError):
            script.import_config(Path("/nonexistent/config.yaml"))

    def test_export_config_creates_file(self):
        script = ConcreteScript()
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "export.yaml"
            script.export_config(export_path)
            self.assertTrue(export_path.exists())

    def test_export_config_path_traversal_rejected(self):
        script = ConcreteScript()
        with self.assertRaises(ValueError):
            script.export_config("../../etc/export.yaml")


class TestScriptBaseSettingsWidget(unittest.TestCase):
    def test_default_returns_none(self):
        script = ConcreteScript()
        self.assertIsNone(script.create_settings_widget())


class TestTrayMenuItem(unittest.TestCase):
    def test_default_values(self):
        item = TrayMenuItem()
        self.assertEqual(item.label, "")
        self.assertIsNone(item.action)
        self.assertIsNone(item.items)
        self.assertIsNone(item.checked)
        self.assertTrue(item.enabled)
        self.assertFalse(item.separator)

    def test_custom_values(self):
        item = TrayMenuItem(label="Test", action=lambda: None, checked=True)
        self.assertEqual(item.label, "Test")
        self.assertIsNotNone(item.action)
        self.assertTrue(item.checked)

    def test_callable_label(self):
        item = TrayMenuItem(label=lambda: "Dynamic")
        self.assertEqual(item.label(), "Dynamic")

    def test_callable_checked(self):
        item = TrayMenuItem(checked=lambda: True)
        self.assertTrue(item.checked())

    def test_callable_enabled(self):
        item = TrayMenuItem(enabled=lambda: False)
        self.assertFalse(item.enabled())

    def test_separator_item(self):
        item = TrayMenuItem(separator=True)
        self.assertTrue(item.separator)


class TestScriptRegistryNewStyleScript(unittest.TestCase):
    def test_load_new_style_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "newstyle.py"
            script_path.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'my_script'\n"
                "    @property\n"
                "    def display_name(self): return 'My Script'\n"
                "    @property\n"
                "    def description(self): return 'Test'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry = registry._load_script_file(script_path)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.script.name, "my_script")

    def test_new_style_script_duplicate_same_path_reloads(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dup.py"
            script_path.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class DupScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'dup'\n"
                "    @property\n"
                "    def display_name(self): return 'Dup'\n"
                "    @property\n"
                "    def description(self): return 'Dup'\n"
                "def create_script(): return DupScript()\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            entry1 = registry._load_script_file(script_path)
            self.assertIsNotNone(entry1)
            entry2 = registry._load_script_file(script_path)
            self.assertIsNotNone(entry2)
            self.assertEqual(len(registry.entries), 1)

    def test_new_style_script_different_path_same_name_skips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script1 = Path(temp_dir) / "dir1" / "conflict.py"
            script1.parent.mkdir(parents=True, exist_ok=True)
            script1.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class ConflictScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'conflict'\n"
                "    @property\n"
                "    def display_name(self): return 'Conflict 1'\n"
                "    @property\n"
                "    def description(self): return 'First'\n"
                "def create_script(): return ConflictScript()\n",
                encoding="utf-8",
            )
            script2 = Path(temp_dir) / "dir2" / "conflict.py"
            script2.parent.mkdir(parents=True, exist_ok=True)
            script2.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class ConflictScript2(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'conflict'\n"
                "    @property\n"
                "    def display_name(self): return 'Conflict 2'\n"
                "    @property\n"
                "    def description(self): return 'Second'\n"
                "def create_script(): return ConflictScript2()\n",
                encoding="utf-8",
            )
            registry = ScriptRegistry()
            registry._load_script_file(script1)
            entry2 = registry._load_script_file(script2)
            self.assertIsNone(entry2)
            self.assertEqual(len(registry.entries), 1)


class TestScriptRegistryGetMethods(unittest.TestCase):
    def test_get_enabled_scripts(self):
        registry = ScriptRegistry()
        script = ConcreteScript()
        registry._entries["test"] = ScriptEntry(script=script, enabled=True)
        registry._entries["disabled"] = ScriptEntry(script=ConcreteScript(), enabled=False)
        enabled = registry.get_enabled_scripts()
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].script.name, "test_script")

    def test_get_all_scripts(self):
        registry = ScriptRegistry()
        registry._entries["a"] = ScriptEntry(script=ConcreteScript(), enabled=True)
        registry._entries["b"] = ScriptEntry(script=ConcreteScript(), enabled=False)
        all_scripts = registry.get_all_scripts()
        self.assertEqual(len(all_scripts), 2)

    def test_get_ocr_scripts(self):
        registry = ScriptRegistry()
        registry._entries["ocr"] = ScriptEntry(script=OcrScript(), enabled=True)
        registry._entries["non_ocr"] = ScriptEntry(script=ConcreteScript(), enabled=True)
        ocr = registry.get_ocr_scripts()
        self.assertEqual(len(ocr), 1)
        self.assertEqual(ocr[0].script.name, "ocr_test")

    def test_get_hotkey_scripts(self):
        registry = ScriptRegistry()
        registry._entries["hotkey"] = ScriptEntry(script=HotkeyScript(), enabled=True)
        registry._entries["no_hotkey"] = ScriptEntry(script=ConcreteScript(), enabled=True)
        hotkey = registry.get_hotkey_scripts()
        self.assertEqual(len(hotkey), 1)
        self.assertEqual(hotkey[0].script.name, "hotkey_test")

    def test_get_existing_script(self):
        registry = ScriptRegistry()
        script = ConcreteScript()
        registry._entries["test"] = ScriptEntry(script=script)
        entry = registry.get("test")
        self.assertIsNotNone(entry)
        self.assertIs(entry.script, script)

    def test_get_nonexistent_script(self):
        registry = ScriptRegistry()
        self.assertIsNone(registry.get("nonexistent"))

    def test_clear(self):
        registry = ScriptRegistry()
        registry._entries["test"] = ScriptEntry(script=ConcreteScript())
        registry.clear()
        self.assertEqual(len(registry.entries), 0)


class TestScriptRegistryConfigs(unittest.TestCase):
    def test_save_configs(self):
        registry = ScriptRegistry()
        script = ConcreteScript()
        registry._entries["test"] = ScriptEntry(script=script, enabled=True)
        configs = registry.save_configs()
        self.assertIn("test", configs)
        self.assertTrue(configs["test"]["enabled"])

    def test_load_configs(self):
        registry = ScriptRegistry()
        script = ConcreteScript()
        registry._entries["test"] = ScriptEntry(script=script, enabled=True)
        registry.load_configs({"test": {"enabled": False}})
        self.assertFalse(registry._entries["test"].enabled)

    def test_load_configs_invalid_type(self):
        registry = ScriptRegistry()
        script = ConcreteScript()
        registry._entries["test"] = ScriptEntry(script=script, enabled=True)
        registry.load_configs({"test": "not_a_dict"})
        self.assertTrue(registry._entries["test"].enabled)

    def test_load_configs_missing_key(self):
        registry = ScriptRegistry()
        script = ConcreteScript()
        registry._entries["test"] = ScriptEntry(script=script, enabled=True)
        registry.load_configs({"nonexistent": {"enabled": False}})
        self.assertTrue(registry._entries["test"].enabled)


class TestScriptRegistryDiscover(unittest.TestCase):
    def test_discover_skips_underscore_prefixed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            (Path(temp_dir) / "_private.py").write_text(
                "def process_image(image_bytes, context): return 'test'\n", encoding="utf-8"
            )
            (Path(temp_dir) / "public.py").write_text(
                "def process_image(image_bytes, context): return 'test'\n", encoding="utf-8"
            )
            registry = ScriptRegistry()
            registry.discover_scripts(Path(temp_dir))
            self.assertNotIn("_private", registry.entries)
            self.assertIn("public", registry.entries)

    def test_discover_nonexistent_dir(self):
        registry = ScriptRegistry()
        registry.discover_scripts(Path("/nonexistent/dir"))
        self.assertEqual(len(registry.entries), 0)


class TestScriptSafetyMorePatterns(unittest.TestCase):
    def test_subprocess_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "subprocess.py"
            script_path.write_text(
                "import subprocess\nsubprocess.run(['ls'])\n"
                "def process_image(image_bytes, context): return 'test'\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(script_path)

    def test_eval_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "eval.py"
            script_path.write_text(
                "eval('1+1')\n"
                "def process_image(image_bytes, context): return 'test'\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(script_path)

    def test_pickle_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "pickle_script.py"
            script_path.write_text(
                "import pickle\npickle.loads(b'')\n"
                "def process_image(image_bytes, context): return 'test'\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(script_path)

    def test_os_popen_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "popen.py"
            script_path.write_text(
                "import os\nos.popen('ls')\n"
                "def process_image(image_bytes, context): return 'test'\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(script_path)

    def test_socket_warning_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "socket_warn.py"
            script_path.write_text(
                "import socket\nsocket.socket()\n"
                "def process_image(image_bytes, context): return 'test'\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertTrue(len(warnings) > 0)
            self.assertEqual(len(blocked), 0)

    def test_os_environ_warning_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "environ.py"
            script_path.write_text(
                "import os\nprint(os.environ)\n"
                "def process_image(image_bytes, context): return 'test'\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertTrue(any("os.environ" in w for w in warnings))
            self.assertEqual(len(blocked), 0)

    def test_safe_script_no_warnings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "safe.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'safe'\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertEqual(len(warnings), 0)
            self.assertEqual(len(blocked), 0)

    def test_check_blocked_patterns_returns_list(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "blocked.py"
            script_path.write_text(
                "exec('print(1)')\n"
                "def process_image(image_bytes, context): return 'test'\n",
                encoding="utf-8",
            )
            blocked = check_blocked_patterns(script_path)
            self.assertIsInstance(blocked, list)
            self.assertIn("exec()", blocked)


class TestExtractLegacyResult(unittest.TestCase):
    def test_string_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "str_result.py"
            script_path.write_text(
                "def process_image(image_bytes, context): return 'x^2'\n",
                encoding="utf-8",
            )
            module = _load_script_module(script_path)
            result = _extract_legacy_result(module, script_path, "x^2")
            self.assertEqual(result, "x^2")

    def test_dict_result_with_latex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dict_result.py"
            script_path.write_text(
                "def process_image(image_bytes, context): return {'latex': 'y^2'}\n",
                encoding="utf-8",
            )
            module = _load_script_module(script_path)
            result = _extract_legacy_result(module, script_path, {"latex": "y^2"})
            self.assertEqual(result, "y^2")

    def test_unsupported_result_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "bad_result.py"
            script_path.write_text(
                "def process_image(image_bytes, context): return 42\n",
                encoding="utf-8",
            )
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, 42)

    def test_empty_string_result_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "empty_result.py"
            script_path.write_text(
                "def process_image(image_bytes, context): return '  '\n",
                encoding="utf-8",
            )
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, "  ")

    def test_dict_without_latex_raises(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "no_latex.py"
            script_path.write_text(
                "def process_image(image_bytes, context): return {'text': 'hello'}\n",
                encoding="utf-8",
            )
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, {"text": "hello"})


class TestValidateScriptPath(unittest.TestCase):
    def test_nonexistent_file(self):
        with self.assertRaises(FileNotFoundError):
            validate_script_path(Path("/nonexistent/script.py"))

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "empty.py"
            script_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(script_path)

    def test_oversized_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "big.py"
            script_path.write_text("x = 1\n" * 200000, encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(script_path)

    def test_path_traversal(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            validate_script_path(Path("../../etc/script.py"))

    def test_valid_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "valid.py"
            script_path.write_text("def process_image(image_bytes, context): return 'test'\n", encoding="utf-8")
            validate_script_path(script_path)


class TestScriptContextAPIs(unittest.TestCase):
    def test_clipboard_api_read_text(self):
        api = ClipboardAPI(
            read_text_fn=lambda: "hello",
            write_text_fn=lambda t: None,
            read_image_fn=lambda: None,
        )
        self.assertEqual(api.read_text(), "hello")

    def test_clipboard_api_write_text(self):
        written = []
        api = ClipboardAPI(
            read_text_fn=lambda: None,
            write_text_fn=lambda t: written.append(t),
            read_image_fn=lambda: None,
        )
        api.write_text("test")
        self.assertEqual(written, ["test"])

    def test_clipboard_api_read_image(self):
        from platex_client.models import ClipboardImage
        img = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        api = ClipboardAPI(
            read_text_fn=lambda: None,
            write_text_fn=lambda t: None,
            read_image_fn=lambda: img,
        )
        self.assertIs(api.read_image(), img)

    def test_hotkey_api_register(self):
        api = HotkeyAPI(
            register_fn=lambda h, cb: True,
            unregister_fn=lambda h: None,
        )
        self.assertTrue(api.register("Ctrl+K", lambda: None))

    def test_hotkey_api_unregister(self):
        unregistered = []
        api = HotkeyAPI(
            register_fn=lambda h, cb: True,
            unregister_fn=lambda h: unregistered.append(h),
        )
        api.unregister("Ctrl+K")
        self.assertEqual(unregistered, ["Ctrl+K"])

    def test_notification_api_show(self):
        shown = []
        api = NotificationAPI(
            show_fn=lambda t, m, ms: shown.append((t, m, ms)),
            show_ocr_fn=lambda l, ms: None,
        )
        api.show("Title", "Message", timeout_ms=3000)
        self.assertEqual(shown, [("Title", "Message", 3000)])

    def test_notification_api_show_ocr_result(self):
        shown = []
        api = NotificationAPI(
            show_fn=lambda t, m, ms: None,
            show_ocr_fn=lambda l, ms: shown.append((l, ms)),
        )
        api.show_ocr_result("x^2", timeout_ms=5000)
        self.assertEqual(shown, [("x^2", 5000)])

    def test_window_api_get_foreground_title(self):
        api = WindowAPI(get_foreground_title_fn=lambda: "Test Window")
        self.assertEqual(api.get_foreground_title(), "Test Window")

    def test_mouse_api_click(self):
        clicked = []
        api = MouseAPI(click_fn=lambda x, y, b: clicked.append((x, y, b)))
        api.click(100, 200, button="right")
        self.assertEqual(clicked, [(100, 200, "right")])

    def test_history_api_latest(self):
        api = HistoryAPI(
            latest_fn=lambda: None,
            list_recent_fn=lambda n: [],
        )
        self.assertIsNone(api.latest())

    def test_history_api_list_recent(self):
        events = [MagicMock()]
        api = HistoryAPI(
            latest_fn=lambda: events[0],
            list_recent_fn=lambda n: events[:n],
        )
        self.assertEqual(len(api.list_recent(1)), 1)

    def test_config_api_get(self):
        api = ConfigAPI(
            get_fn=lambda k, d: d,
            set_fn=lambda k, v: None,
            save_fn=lambda: None,
            get_all_fn=lambda: {},
        )
        self.assertEqual(api.get("key", "default"), "default")

    def test_config_api_set(self):
        set_calls = []
        api = ConfigAPI(
            get_fn=lambda k, d: None,
            set_fn=lambda k, v: set_calls.append((k, v)),
            save_fn=lambda: None,
            get_all_fn=lambda: {},
        )
        api.set("key", "value")
        self.assertEqual(set_calls, [("key", "value")])

    def test_config_api_save(self):
        saved = []
        api = ConfigAPI(
            get_fn=lambda k, d: None,
            set_fn=lambda k, v: None,
            save_fn=lambda: saved.append(True),
            get_all_fn=lambda: {},
        )
        api.save()
        self.assertEqual(saved, [True])

    def test_config_api_get_all(self):
        api = ConfigAPI(
            get_fn=lambda k, d: None,
            set_fn=lambda k, v: None,
            save_fn=lambda: None,
            get_all_fn=lambda: {"key": "val"},
        )
        self.assertEqual(api.get_all(), {"key": "val"})

    def test_logger_api_get(self):
        api = LoggerAPI()
        logger = api.get("test_script")
        self.assertEqual(logger.name, "platex.script.test_script")


class TestScriptContextShutdown(unittest.TestCase):
    def test_shutdown_cancels_scheduler(self):
        scheduler = SchedulerAPI()
        ctx = ScriptContext(
            clipboard=MagicMock(),
            hotkeys=MagicMock(),
            notifications=MagicMock(),
            windows=MagicMock(),
            mouse=MagicMock(),
            scheduler=scheduler,
            history=MagicMock(),
            config=MagicMock(),
            logger=LoggerAPI(),
        )
        task = scheduler.schedule_once(10.0, lambda: None)
        ctx.shutdown()
        self.assertTrue(task.is_cancelled)


if __name__ == "__main__":
    unittest.main()
