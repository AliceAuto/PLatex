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
from platex_client.script_registry import ScriptEntry, ScriptRegistry
from platex_client.script_safety import (
    _BLOCKED_PATTERNS,
    _DANGEROUS_PATTERNS,
    _MAX_SCRIPT_FILE_SIZE,
    _check_dangerous_patterns,
    _extract_legacy_result,
    _load_script_module,
    check_blocked_patterns,
    scan_script_source,
    validate_script_path,
)


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


class TestScriptBase(unittest.TestCase):
    def _make_script(self):
        return ConcreteScript()

    def test_name_property(self):
        script = self._make_script()
        self.assertEqual(script.name, "test_script")

    def test_display_name_property(self):
        script = self._make_script()
        self.assertEqual(script.display_name, "Test Script")

    def test_description_property(self):
        script = self._make_script()
        self.assertEqual(script.description, "A test script")

    def test_context_default_none(self):
        script = self._make_script()
        self.assertIsNone(script.context)

    def test_on_context_ready(self):
        script = self._make_script()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        self.assertEqual(script.context, ctx)

    def test_create_settings_widget_default_none(self):
        script = self._make_script()
        self.assertIsNone(script.create_settings_widget())

    def test_get_hotkey_bindings_default_empty(self):
        script = self._make_script()
        self.assertEqual(script.get_hotkey_bindings(), {})

    def test_on_hotkey_default_noop(self):
        script = self._make_script()
        script.on_hotkey("test")

    def test_passthrough_hotkeys_default_false(self):
        script = self._make_script()
        self.assertFalse(script.passthrough_hotkeys)

    def test_has_ocr_capability_default_false(self):
        script = self._make_script()
        self.assertFalse(script.has_ocr_capability())

    def test_process_image_without_capability_raises(self):
        script = self._make_script()
        with self.assertRaises(RuntimeError):
            script.process_image(b"fake", {})

    def test_get_tray_menu_items_default_empty(self):
        script = self._make_script()
        self.assertEqual(script.get_tray_menu_items(), [])

    def test_set_tray_action_callback(self):
        script = self._make_script()
        cb = lambda a, p: None
        script.set_tray_action_callback(cb)
        self.assertEqual(script._tray_action_callback, cb)

    def test_test_connection_default(self):
        script = self._make_script()
        result = script.test_connection()
        self.assertEqual(result, (True, "OK"))

    def test_load_config_default_noop(self):
        script = self._make_script()
        script.load_config({"key": "value"})

    def test_save_config_default_empty(self):
        script = self._make_script()
        self.assertEqual(script.save_config(), {})

    def test_activate_default_noop(self):
        script = self._make_script()
        script.activate()

    def test_deactivate(self):
        script = self._make_script()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        script.deactivate()
        self.assertIsNone(script.context)

    def test_deactivate_no_context(self):
        script = self._make_script()
        script.deactivate()

    def test_notify_hotkeys_changed_no_callback(self):
        script = self._make_script()
        script._notify_hotkeys_changed()

    def test_notify_hotkeys_changed_with_callback(self):
        script = self._make_script()
        called = threading.Event()
        script.set_hotkeys_changed_callback(called.set)
        script._notify_hotkeys_changed()
        self.assertTrue(called.is_set())

    def test_notify_hotkeys_changed_callback_exception(self):
        script = self._make_script()
        script.set_hotkeys_changed_callback(lambda: (_ for _ in ()).throw(RuntimeError("error")))
        script._notify_hotkeys_changed()

    def test_validate_config_path_normal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            p = Path(temp_dir) / "config.yaml"
            p.write_text("key: value", encoding="utf-8")
            result = ScriptBase._validate_config_path(p)
            self.assertIsNotNone(result)

    def test_validate_config_path_traversal(self):
        with self.assertRaises(ValueError):
            ScriptBase._validate_config_path(Path("../../etc/config.yaml"))

    def test_import_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("key: value\n", encoding="utf-8")
            script = self._make_script()
            result = script.import_config(config_path)
            self.assertEqual(result, {"key": "value"})

    def test_import_config_nonexistent(self):
        script = self._make_script()
        with self.assertRaises(FileNotFoundError):
            script.import_config(Path("/nonexistent/config.yaml"))

    def test_export_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            export_path = Path(temp_dir) / "export.yaml"
            script = self._make_script()
            script.export_config(export_path)
            self.assertTrue(export_path.exists())


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

    def test_separator(self):
        item = TrayMenuItem(separator=True)
        self.assertTrue(item.separator)


class TestSchedulerAPIComprehensive(unittest.TestCase):
    def test_schedule_once_fires(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        scheduler.schedule_once(0.1, fired.set)
        self.assertTrue(fired.wait(timeout=2.0))
        scheduler.cancel_all()

    def test_schedule_once_cancel(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        task = scheduler.schedule_once(0.5, fired.set)
        task.cancel()
        time.sleep(0.8)
        self.assertFalse(fired.is_set())
        scheduler.cancel_all()

    def test_schedule_repeating_fires(self):
        scheduler = SchedulerAPI()
        count = {"value": 0}
        count_event = threading.Event()

        def increment():
            count["value"] += 1
            if count["value"] >= 3:
                count_event.set()

        task = scheduler.schedule_repeating(0.1, increment)
        self.assertTrue(count_event.wait(timeout=5.0))
        self.assertGreaterEqual(count["value"], 3)
        task.cancel()
        scheduler.cancel_all()

    def test_schedule_repeating_cancel(self):
        scheduler = SchedulerAPI()
        count = {"value": 0}

        def increment():
            count["value"] += 1

        task = scheduler.schedule_repeating(0.1, increment)
        time.sleep(0.35)
        task.cancel()
        count_after_cancel = count["value"]
        time.sleep(0.3)
        self.assertEqual(count["value"], count_after_cancel)
        scheduler.cancel_all()

    def test_cancel_all(self):
        scheduler = SchedulerAPI()
        fired1 = threading.Event()
        fired2 = threading.Event()
        scheduler.schedule_once(0.3, fired1.set)
        scheduler.schedule_once(0.3, fired2.set)
        scheduler.cancel_all()
        time.sleep(0.5)
        self.assertFalse(fired1.is_set())
        self.assertFalse(fired2.is_set())

    def test_max_task_limit(self):
        scheduler = SchedulerAPI()
        tasks = []
        try:
            for _ in range(64):
                task = scheduler.schedule_once(10.0, lambda: None)
                tasks.append(task)
            with self.assertRaises(RuntimeError):
                scheduler.schedule_once(10.0, lambda: None)
        finally:
            scheduler.cancel_all()

    def test_cancel_already_fired_task(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        task = scheduler.schedule_once(0.05, fired.set)
        self.assertTrue(fired.wait(timeout=2.0))
        task.cancel()
        scheduler.cancel_all()

    def test_double_cancel(self):
        scheduler = SchedulerAPI()
        task = scheduler.schedule_once(10.0, lambda: None)
        task.cancel()
        task.cancel()
        scheduler.cancel_all()

    def test_callback_exception_does_not_break(self):
        scheduler = SchedulerAPI()
        good_called = threading.Event()

        def bad_cb():
            raise RuntimeError("callback error")

        def good_cb():
            good_called.set()

        scheduler.schedule_once(0.05, bad_cb)
        scheduler.schedule_once(0.1, good_cb)
        self.assertTrue(good_called.wait(timeout=3.0))
        scheduler.cancel_all()

    def test_min_delay_clamped(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        scheduler.schedule_once(0.001, fired.set)
        self.assertTrue(fired.wait(timeout=2.0))
        scheduler.cancel_all()

    def test_scheduled_task_is_cancelled_property(self):
        scheduler = SchedulerAPI()
        task = scheduler.schedule_once(10.0, lambda: None)
        self.assertFalse(task.is_cancelled)
        task.cancel()
        self.assertTrue(task.is_cancelled)
        scheduler.cancel_all()


class TestScriptSafety(unittest.TestCase):
    def test_validate_nonexistent_file(self):
        with self.assertRaises(FileNotFoundError):
            validate_script_path(Path("/nonexistent/script.py"))

    def test_validate_empty_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "empty.py"
            script_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(script_path)

    def test_validate_oversized_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "big.py"
            script_path.write_text("x = 1\n" * 200000, encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(script_path)

    def test_validate_normal_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "normal.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            validate_script_path(script_path)

    def test_scan_safe_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "safe.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'safe result'\n", encoding="utf-8")
            warnings, blocked = scan_script_source(script_path)
            self.assertEqual(len(blocked), 0)
            self.assertEqual(len(warnings), 0)

    def test_scan_dangerous_os_system(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dangerous.py"
            script_path.write_text("import os\nos.system('echo pwned')\n", encoding="utf-8")
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("os.system", blocked)

    def test_scan_dangerous_subprocess(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "sub.py"
            script_path.write_text("import subprocess\nsubprocess.run(['ls'])\n", encoding="utf-8")
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("subprocess execution", blocked)

    def test_scan_dangerous_exec(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "exec.py"
            script_path.write_text("exec('print(1)')\n", encoding="utf-8")
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("exec()", blocked)

    def test_scan_dangerous_eval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "eval.py"
            script_path.write_text("eval('1+1')\n", encoding="utf-8")
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("eval()", blocked)

    def test_scan_dangerous_pickle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "pickle.py"
            script_path.write_text("import pickle\npickle.loads(b'data')\n", encoding="utf-8")
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("pickle deserialization", blocked)

    def test_scan_warning_socket(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "socket.py"
            script_path.write_text("import socket\nsocket.socket()\n", encoding="utf-8")
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("socket access", warnings)

    def test_check_dangerous_patterns_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dangerous.py"
            script_path.write_text("import os\nos.system('echo pwned')\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(script_path)

    def test_check_dangerous_patterns_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "safe.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'safe'\n", encoding="utf-8")
            _check_dangerous_patterns(script_path)

    def test_check_blocked_patterns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "evil.py"
            script_path.write_text("exec('print(1)')\n", encoding="utf-8")
            blocked = check_blocked_patterns(script_path)
            self.assertIn("exec()", blocked)

    def test_load_script_module_syntax_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "bad_syntax.py"
            script_path.write_text("def broken(\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _load_script_module(script_path)

    def test_load_script_module_runtime_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "runtime_error.py"
            script_path.write_text("raise RuntimeError('init error')\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _load_script_module(script_path)

    def test_load_script_module_success(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "good.py"
            script_path.write_text("VALUE = 42\n", encoding="utf-8")
            module = _load_script_module(script_path)
            self.assertEqual(module.VALUE, 42)

    def test_extract_legacy_result_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            result = _extract_legacy_result(module, script_path, "x^2 + y^2")
            self.assertEqual(result, "x^2 + y^2")

    def test_extract_legacy_result_dict(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            result = _extract_legacy_result(module, script_path, {"latex": "x^2"})
            self.assertEqual(result, "x^2")

    def test_extract_legacy_result_unsupported_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, 42)

    def test_extract_legacy_result_empty_string(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, "  ")

    def test_extract_legacy_result_whitespace_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, "  \n  ")


class TestScriptRegistry(unittest.TestCase):
    def test_empty_registry(self):
        registry = ScriptRegistry()
        self.assertEqual(len(registry.entries), 0)
        self.assertEqual(registry.get_ocr_scripts(), [])
        self.assertEqual(registry.get_hotkey_scripts(), [])
        self.assertEqual(registry.get_enabled_scripts(), [])
        self.assertEqual(registry.get_all_scripts(), [])

    def test_load_nonexistent_script(self):
        registry = ScriptRegistry()
        result = registry.load_script_file(Path("/nonexistent/script.py"))
        self.assertIsNone(result)

    def test_discover_from_nonexistent_dir(self):
        registry = ScriptRegistry()
        registry.discover_scripts(Path("/nonexistent/scripts"))

    def test_load_safe_script(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "safe.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            registry = ScriptRegistry()
            entry = registry._load_script_file(script_path)
            self.assertIsNotNone(entry)
            self.assertTrue(entry.script.has_ocr_capability())

    def test_load_dangerous_script_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dangerous.py"
            script_path.write_text("import os\nos.system('echo pwned')\n", encoding="utf-8")
            registry = ScriptRegistry()
            with self.assertRaises(ValueError):
                registry._load_script_file(script_path)

    def test_load_script_no_interface(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "no_interface.py"
            script_path.write_text("x = 42\n", encoding="utf-8")
            registry = ScriptRegistry()
            result = registry._load_script_file(script_path)
            self.assertIsNone(result)

    def test_load_script_with_create_script(self):
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

    def test_duplicate_script_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = ScriptRegistry()
            script1 = Path(temp_dir) / "myscript.py"
            script1.write_text("def process_image(image_bytes, context):\n    return 'script1'\n", encoding="utf-8")
            script2 = Path(temp_dir) / "subdir" / "myscript.py"
            script2.parent.mkdir(parents=True, exist_ok=True)
            script2.write_text("def process_image(image_bytes, context):\n    return 'script2'\n", encoding="utf-8")
            registry._load_script_file(script1)
            registry._load_script_file(script2)
            self.assertEqual(len(registry.entries), 1)

    def test_get_ocr_scripts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "ocr.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(script_path)
            ocr_scripts = registry.get_ocr_scripts()
            self.assertGreaterEqual(len(ocr_scripts), 1)

    def test_get_hotkey_scripts_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "no_hotkey.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(script_path)
            self.assertEqual(len(registry.get_hotkey_scripts()), 0)

    def test_load_configs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(script_path)
            registry.load_configs({"test": {"enabled": False}})
            entry = registry.get("test")
            self.assertFalse(entry.enabled)

    def test_load_configs_invalid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(script_path)
            registry.load_configs({"test": "not_a_dict"})

    def test_save_configs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(script_path)
            configs = registry.save_configs()
            self.assertIn("test", configs)
            self.assertTrue(configs["test"]["enabled"])

    def test_clear(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(script_path)
            registry.clear()
            self.assertEqual(len(registry.entries), 0)

    def test_get_method(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text("def process_image(image_bytes, context):\n    return 'test'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry._load_script_file(script_path)
            entry = registry.get("test")
            self.assertIsNotNone(entry)
            self.assertIsNone(registry.get("nonexistent"))

    def test_discover_scripts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            scripts_dir = Path(temp_dir) / "scripts"
            scripts_dir.mkdir()
            (scripts_dir / "script1.py").write_text("def process_image(image_bytes, context):\n    return 'test1'\n", encoding="utf-8")
            (scripts_dir / "script2.py").write_text("def process_image(image_bytes, context):\n    return 'test2'\n", encoding="utf-8")
            (scripts_dir / "_private.py").write_text("def process_image(image_bytes, context):\n    return 'private'\n", encoding="utf-8")
            registry = ScriptRegistry()
            registry.discover_scripts(scripts_dir)
            self.assertIn("script1", registry.entries)
            self.assertIn("script2", registry.entries)
            self.assertNotIn("_private", registry.entries)


class TestScriptContextAPIs(unittest.TestCase):
    def test_clipboard_api(self):
        api = ClipboardAPI(
            read_text_fn=lambda: "hello",
            write_text_fn=lambda t: None,
            read_image_fn=lambda: None,
        )
        self.assertEqual(api.read_text(), "hello")

    def test_hotkey_api(self):
        registered = []
        api = HotkeyAPI(
            register_fn=lambda h, cb: (registered.append(h), True)[1],
            unregister_fn=lambda h: registered.remove(h) if h in registered else None,
        )
        self.assertTrue(api.register("Ctrl+A", lambda: None))
        api.unregister("Ctrl+A")

    def test_notification_api(self):
        shown = []
        api = NotificationAPI(
            show_fn=lambda t, m, ms: shown.append((t, m)),
            show_ocr_fn=lambda l, ms: shown.append(("ocr", l)),
        )
        api.show("Title", "Message")
        api.show_ocr_result("x^2")
        self.assertEqual(len(shown), 2)

    def test_window_api(self):
        api = WindowAPI(get_foreground_title_fn=lambda: "Test Window")
        self.assertEqual(api.get_foreground_title(), "Test Window")

    def test_mouse_api(self):
        clicks = []
        api = MouseAPI(click_fn=lambda x, y, b: clicks.append((x, y, b)))
        api.click(100, 200, "left")
        self.assertEqual(clicks, [(100, 200, "left")])

    def test_history_api(self):
        api = HistoryAPI(
            latest_fn=lambda: None,
            list_recent_fn=lambda limit: [],
        )
        self.assertIsNone(api.latest())
        self.assertEqual(api.list_recent(), [])

    def test_config_api(self):
        config_data = {"key": "value"}

        def get_fn(k, default=None):
            return config_data.get(k, default)

        def set_fn(k, v):
            config_data[k] = v

        api = ConfigAPI(get_fn=get_fn, set_fn=set_fn, save_fn=lambda: None, get_all_fn=lambda: dict(config_data))
        self.assertEqual(api.get("key"), "value")
        self.assertEqual(api.get("missing", "default"), "default")
        api.set("new_key", "new_value")
        self.assertEqual(api.get("new_key"), "new_value")
        self.assertEqual(api.get_all(), {"key": "value", "new_key": "new_value"})

    def test_logger_api(self):
        api = LoggerAPI()
        logger = api.get("test_script")
        self.assertIsNotNone(logger)

    def test_script_context_shutdown(self):
        ctx = ScriptContext(
            clipboard=ClipboardAPI(read_text_fn=lambda: None, write_text_fn=lambda t: None, read_image_fn=lambda: None),
            hotkeys=HotkeyAPI(register_fn=lambda h, cb: True, unregister_fn=lambda h: None),
            notifications=NotificationAPI(show_fn=lambda t, m, ms: None, show_ocr_fn=lambda l, ms: None),
            windows=WindowAPI(get_foreground_title_fn=lambda: ""),
            mouse=MouseAPI(click_fn=lambda x, y, b: None),
            scheduler=SchedulerAPI(),
            history=HistoryAPI(latest_fn=lambda: None, list_recent_fn=lambda limit: []),
            config=ConfigAPI(get_fn=lambda k, d: d, set_fn=lambda k, v: None, save_fn=lambda: None, get_all_fn=lambda: {}),
            logger=LoggerAPI(),
        )
        ctx.shutdown()


if __name__ == "__main__":
    unittest.main()
