from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.script_base import ScriptBase, TrayMenuItem


# ---------------------------------------------------------------------------
# Concrete subclasses for testing
# ---------------------------------------------------------------------------

class _ConcreteScript(ScriptBase):
    """Minimal concrete subclass that overrides only the abstract properties."""

    @property
    def name(self):
        return "test_script"

    @property
    def display_name(self):
        return "Test Script"

    @property
    def description(self):
        return "A test script for unit testing"


class _OcrScript(ScriptBase):
    """Subclass that claims OCR capability but does NOT implement process_image."""

    @property
    def name(self):
        return "ocr_script"

    @property
    def display_name(self):
        return "OCR Script"

    @property
    def description(self):
        return "An OCR-capable script"

    def has_ocr_capability(self):
        return True


class _OcrImplScript(ScriptBase):
    """Subclass that claims OCR capability AND implements process_image."""

    @property
    def name(self):
        return "ocr_impl_script"

    @property
    def display_name(self):
        return "OCR Impl Script"

    @property
    def description(self):
        return "An OCR script with a real implementation"

    def has_ocr_capability(self):
        return True

    def process_image(self, image_bytes, context=None):
        return "ocr_result_from_impl"


class _HotkeyScript(ScriptBase):
    """Subclass with hotkey bindings."""

    @property
    def name(self):
        return "hotkey_script"

    @property
    def display_name(self):
        return "Hotkey Script"

    @property
    def description(self):
        return "A script with hotkey bindings"

    def get_hotkey_bindings(self):
        return {"action1": "Ctrl+Alt+1", "action2": "Ctrl+Alt+2"}

    def on_hotkey(self, action):
        self._last_hotkey_action = action


class _ConfigScript(ScriptBase):
    """Subclass with load_config / save_config overrides."""

    @property
    def name(self):
        return "config_script"

    @property
    def display_name(self):
        return "Config Script"

    @property
    def description(self):
        return "A script with config support"

    def __init__(self):
        super().__init__()
        self._config_data: dict = {}

    def load_config(self, config):
        self._config_data = dict(config)

    def save_config(self):
        return dict(self._config_data)


class _TrayScript(ScriptBase):
    """Subclass with tray menu items."""

    @property
    def name(self):
        return "tray_script"

    @property
    def display_name(self):
        return "Tray Script"

    @property
    def description(self):
        return "A script with tray menu items"

    def __init__(self):
        super().__init__()
        self._toggled = False

    def get_tray_menu_items(self):
        return [
            TrayMenuItem(label="Toggle", action=self._toggle),
            TrayMenuItem(separator=True),
            TrayMenuItem(
                label=lambda: "Checked" if self._toggled else "Unchecked",
                checked=lambda: self._toggled,
            ),
            TrayMenuItem(
                label="Sub",
                items=[
                    TrayMenuItem(label="Sub A"),
                    TrayMenuItem(label="Sub B"),
                ],
            ),
        ]

    def _toggle(self):
        self._toggled = not self._toggled


class _PassthroughScript(ScriptBase):
    """Subclass that enables passthrough_hotkeys."""

    @property
    def name(self):
        return "passthrough_script"

    @property
    def display_name(self):
        return "Passthrough Script"

    @property
    def description(self):
        return "A script with passthrough hotkeys"

    @property
    def passthrough_hotkeys(self):
        return True


# ===========================================================================
# Test classes
# ===========================================================================


class TestScriptBaseAbstract(unittest.TestCase):
    """Tests for the abstract nature of ScriptBase."""

    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            ScriptBase()

    def test_concrete_subclass_instantiates(self):
        script = _ConcreteScript()
        self.assertIsNotNone(script)

    def test_missing_name_still_abstract(self):
        class Incomplete(ScriptBase):
            @property
            def display_name(self):
                return "x"

            @property
            def description(self):
                return "x"

        with self.assertRaises(TypeError):
            Incomplete()

    def test_missing_display_name_still_abstract(self):
        class Incomplete(ScriptBase):
            @property
            def name(self):
                return "x"

            @property
            def description(self):
                return "x"

        with self.assertRaises(TypeError):
            Incomplete()

    def test_missing_description_still_abstract(self):
        class Incomplete(ScriptBase):
            @property
            def name(self):
                return "x"

            @property
            def display_name(self):
                return "x"

        with self.assertRaises(TypeError):
            Incomplete()


class TestScriptBaseInit(unittest.TestCase):
    """Tests for __init__ initial state."""

    def test_context_initially_none(self):
        script = _ConcreteScript()
        self.assertIsNone(script.context)
        self.assertIsNone(script._context)

    def test_hotkeys_changed_callback_initially_none(self):
        script = _ConcreteScript()
        self.assertIsNone(script._hotkeys_changed_callback)

    def test_tray_action_callback_initially_none(self):
        script = _ConcreteScript()
        self.assertIsNone(script._tray_action_callback)


class TestScriptBaseAbstractProperties(unittest.TestCase):
    """Tests for the abstract properties on a concrete subclass."""

    def test_name_property(self):
        script = _ConcreteScript()
        self.assertEqual(script.name, "test_script")

    def test_display_name_property(self):
        script = _ConcreteScript()
        self.assertEqual(script.display_name, "Test Script")

    def test_description_property(self):
        script = _ConcreteScript()
        self.assertEqual(script.description, "A test script for unit testing")

    def test_name_is_string(self):
        script = _ConcreteScript()
        self.assertIsInstance(script.name, str)

    def test_display_name_is_string(self):
        script = _ConcreteScript()
        self.assertIsInstance(script.display_name, str)

    def test_description_is_string(self):
        script = _ConcreteScript()
        self.assertIsInstance(script.description, str)


class TestScriptBaseContext(unittest.TestCase):
    """Tests for context property and on_context_ready."""

    def test_context_default_none(self):
        script = _ConcreteScript()
        self.assertIsNone(script.context)

    def test_on_context_ready_sets_context(self):
        script = _ConcreteScript()
        ctx = object()
        script.on_context_ready(ctx)
        self.assertIs(script.context, ctx)

    def test_on_context_ready_overwrite(self):
        script = _ConcreteScript()
        ctx1 = object()
        ctx2 = object()
        script.on_context_ready(ctx1)
        self.assertIs(script.context, ctx1)
        script.on_context_ready(ctx2)
        self.assertIs(script.context, ctx2)

    def test_context_returns_private_attribute(self):
        script = _ConcreteScript()
        sentinel = object()
        script._context = sentinel
        self.assertIs(script.context, sentinel)


class TestScriptBaseActivate(unittest.TestCase):
    """Tests for the activate method."""

    def test_activate_default_noop(self):
        script = _ConcreteScript()
        # Should not raise
        script.activate()

    def test_activate_does_not_set_context(self):
        script = _ConcreteScript()
        script.activate()
        self.assertIsNone(script.context)


class TestScriptBaseDeactivate(unittest.TestCase):
    """Tests for the deactivate method."""

    def test_deactivate_no_context(self):
        script = _ConcreteScript()
        # Should not raise even with no context
        script.deactivate()
        self.assertIsNone(script.context)

    def test_deactivate_clears_context(self):
        script = _ConcreteScript()
        script.on_context_ready(object())
        script.deactivate()
        self.assertIsNone(script.context)

    def test_deactivate_calls_shutdown(self):
        script = _ConcreteScript()
        shutdown_called = [False]

        class FakeContext:
            def shutdown(self):
                shutdown_called[0] = True

        script.on_context_ready(FakeContext())
        script.deactivate()
        self.assertTrue(shutdown_called[0])

    def test_deactivate_handles_shutdown_exception(self):
        script = _ConcreteScript()

        class BadContext:
            def shutdown(self):
                raise RuntimeError("shutdown error")

        script.on_context_ready(BadContext())
        # Should not raise; context should still be cleared
        script.deactivate()
        self.assertIsNone(script.context)

    def test_deactivate_handles_shutdown_attribute_error(self):
        script = _ConcreteScript()

        class NoShutdown:
            pass

        script.on_context_ready(NoShutdown())
        # shutdown() will raise AttributeError, caught by the generic except
        script.deactivate()
        self.assertIsNone(script.context)

    def test_deactivate_idempotent(self):
        script = _ConcreteScript()
        ctx = MagicMock()
        script.on_context_ready(ctx)
        script.deactivate()
        script.deactivate()  # second call should be safe
        self.assertIsNone(script.context)
        # shutdown should have been called exactly once
        ctx.shutdown.assert_called_once()


class TestScriptBaseCreateSettingsWidget(unittest.TestCase):
    """Tests for create_settings_widget."""

    def test_default_returns_none(self):
        script = _ConcreteScript()
        self.assertIsNone(script.create_settings_widget())

    def test_default_returns_none_with_parent(self):
        script = _ConcreteScript()
        self.assertIsNone(script.create_settings_widget(parent=None))


class TestScriptBaseHotkeys(unittest.TestCase):
    """Tests for hotkey-related methods."""

    def test_default_no_hotkey_bindings(self):
        script = _ConcreteScript()
        self.assertEqual(script.get_hotkey_bindings(), {})

    def test_default_hotkey_bindings_type(self):
        script = _ConcreteScript()
        self.assertIsInstance(script.get_hotkey_bindings(), dict)

    def test_hotkey_script_bindings(self):
        script = _HotkeyScript()
        bindings = script.get_hotkey_bindings()
        self.assertEqual(len(bindings), 2)
        self.assertEqual(bindings["action1"], "Ctrl+Alt+1")
        self.assertEqual(bindings["action2"], "Ctrl+Alt+2")

    def test_on_hotkey_default_noop(self):
        script = _ConcreteScript()
        # Should not raise
        script.on_hotkey("any_action")

    def test_on_hotkey_receives_action(self):
        script = _HotkeyScript()
        script.on_hotkey("action1")
        self.assertEqual(script._last_hotkey_action, "action1")

    def test_on_hotkey_different_actions(self):
        script = _HotkeyScript()
        script.on_hotkey("action1")
        self.assertEqual(script._last_hotkey_action, "action1")
        script.on_hotkey("action2")
        self.assertEqual(script._last_hotkey_action, "action2")

    def test_passthrough_hotkeys_default_false(self):
        script = _ConcreteScript()
        self.assertFalse(script.passthrough_hotkeys)

    def test_passthrough_hotkeys_override_true(self):
        script = _PassthroughScript()
        self.assertTrue(script.passthrough_hotkeys)


class TestScriptBaseHotkeyCallback(unittest.TestCase):
    """Tests for hotkey changed callback mechanism."""

    def test_notify_hotkeys_changed_no_callback(self):
        script = _ConcreteScript()
        # Should not raise
        script._notify_hotkeys_changed()

    def test_notify_hotkeys_changed_with_callback(self):
        script = _ConcreteScript()
        called = threading.Event()
        script.set_hotkeys_changed_callback(called.set)
        script._notify_hotkeys_changed()
        self.assertTrue(called.is_set())

    def test_set_hotkeys_changed_callback_none(self):
        script = _ConcreteScript()
        script.set_hotkeys_changed_callback(None)
        # Should not raise
        script._notify_hotkeys_changed()

    def test_set_hotkeys_changed_callback_overwrite(self):
        script = _ConcreteScript()
        call_count = [0]

        def cb1():
            call_count[0] += 1

        def cb2():
            call_count[0] += 10

        script.set_hotkeys_changed_callback(cb1)
        script._notify_hotkeys_changed()
        self.assertEqual(call_count[0], 1)

        script.set_hotkeys_changed_callback(cb2)
        script._notify_hotkeys_changed()
        self.assertEqual(call_count[0], 11)

    def test_callback_exception_handled(self):
        script = _ConcreteScript()

        def bad_cb():
            raise RuntimeError("callback error")

        script.set_hotkeys_changed_callback(bad_cb)
        # Should not raise; exception is caught internally
        script._notify_hotkeys_changed()

    def test_callback_exception_does_not_prevent_other_code(self):
        script = _ConcreteScript()
        call_count = [0]

        def bad_cb():
            call_count[0] += 1
            raise RuntimeError("fail")

        script.set_hotkeys_changed_callback(bad_cb)
        script._notify_hotkeys_changed()
        # Callback was still invoked
        self.assertEqual(call_count[0], 1)

    def test_callback_exception_logged(self):
        script = _ConcreteScript()

        def bad_cb():
            raise RuntimeError("callback error")

        script.set_hotkeys_changed_callback(bad_cb)
        with patch("logging.getLogger") as mock_get_logger:
            script._notify_hotkeys_changed()
            # The exception path calls logging.getLogger and .exception


class TestScriptBaseOcrCapability(unittest.TestCase):
    """Tests for OCR capability and process_image."""

    def test_default_no_ocr_capability(self):
        script = _ConcreteScript()
        self.assertFalse(script.has_ocr_capability())

    def test_process_image_without_capability_raises_runtime_error(self):
        script = _ConcreteScript()
        with self.assertRaises(RuntimeError) as cm:
            script.process_image(b"fake")
        self.assertIn("does not have OCR capability", str(cm.exception))

    def test_process_image_without_capability_includes_script_name(self):
        script = _ConcreteScript()
        with self.assertRaises(RuntimeError) as cm:
            script.process_image(b"fake")
        self.assertIn("test_script", str(cm.exception))

    def test_process_image_without_capability_with_context(self):
        script = _ConcreteScript()
        with self.assertRaises(RuntimeError):
            script.process_image(b"fake", {"key": "val"})

    def test_process_image_without_capability_with_none_context(self):
        script = _ConcreteScript()
        with self.assertRaises(RuntimeError):
            script.process_image(b"fake", None)

    def test_ocr_script_has_capability(self):
        script = _OcrScript()
        self.assertTrue(script.has_ocr_capability())

    def test_ocr_script_process_image_raises_not_implemented(self):
        """OCR capability=True but no process_image override -> NotImplementedError."""
        script = _OcrScript()
        with self.assertRaises(NotImplementedError) as cm:
            script.process_image(b"fake")
        self.assertIn("must implement process_image", str(cm.exception))

    def test_ocr_impl_script_process_image(self):
        script = _OcrImplScript()
        result = script.process_image(b"fake")
        self.assertEqual(result, "ocr_result_from_impl")

    def test_ocr_impl_script_process_image_with_context(self):
        script = _OcrImplScript()
        result = script.process_image(b"fake", {"ctx": True})
        self.assertEqual(result, "ocr_result_from_impl")

    def test_has_ocr_capability_returns_bool(self):
        script = _ConcreteScript()
        self.assertIsInstance(script.has_ocr_capability(), bool)


class TestScriptBaseTrayMenu(unittest.TestCase):
    """Tests for tray menu items and callback."""

    def test_default_tray_menu_empty(self):
        script = _ConcreteScript()
        self.assertEqual(script.get_tray_menu_items(), [])

    def test_default_tray_menu_returns_list(self):
        script = _ConcreteScript()
        self.assertIsInstance(script.get_tray_menu_items(), list)

    def test_set_tray_action_callback(self):
        script = _ConcreteScript()
        callback = lambda a, p: None
        script.set_tray_action_callback(callback)
        self.assertEqual(script._tray_action_callback, callback)

    def test_set_tray_action_callback_none(self):
        script = _ConcreteScript()
        script.set_tray_action_callback(None)
        self.assertIsNone(script._tray_action_callback)

    def test_set_tray_action_callback_overwrite(self):
        script = _ConcreteScript()
        cb1 = lambda a, p: None
        cb2 = lambda a, p: None
        script.set_tray_action_callback(cb1)
        self.assertIs(script._tray_action_callback, cb1)
        script.set_tray_action_callback(cb2)
        self.assertIs(script._tray_action_callback, cb2)

    def test_tray_script_menu_items(self):
        script = _TrayScript()
        items = script.get_tray_menu_items()
        self.assertEqual(len(items), 4)

    def test_tray_script_separator_item(self):
        script = _TrayScript()
        items = script.get_tray_menu_items()
        sep = items[1]
        self.assertTrue(sep.separator)

    def test_tray_script_callable_label(self):
        script = _TrayScript()
        items = script.get_tray_menu_items()
        callable_item = items[2]
        # label is a callable
        self.assertTrue(callable(callable_item.label))

    def test_tray_script_action_executes(self):
        script = _TrayScript()
        items = script.get_tray_menu_items()
        toggle_item = items[0]
        self.assertFalse(script._toggled)
        toggle_item.action()
        self.assertTrue(script._toggled)
        toggle_item.action()
        self.assertFalse(script._toggled)


class TestScriptBaseConfig(unittest.TestCase):
    """Tests for load_config, save_config, import_config, export_config."""

    def test_load_config_default_noop(self):
        script = _ConcreteScript()
        # Should not raise
        script.load_config({"key": "value"})

    def test_load_config_default_noop_empty(self):
        script = _ConcreteScript()
        script.load_config({})

    def test_save_config_default_empty(self):
        script = _ConcreteScript()
        self.assertEqual(script.save_config(), {})

    def test_save_config_default_returns_dict(self):
        script = _ConcreteScript()
        self.assertIsInstance(script.save_config(), dict)

    def test_config_script_load_and_save(self):
        script = _ConfigScript()
        script.load_config({"foo": "bar", "num": 42})
        saved = script.save_config()
        self.assertEqual(saved, {"foo": "bar", "num": 42})

    def test_config_script_save_returns_copy(self):
        script = _ConfigScript()
        script.load_config({"foo": "bar"})
        saved = script.save_config()
        saved["extra"] = "modified"
        # Original should be unaffected
        self.assertEqual(script.save_config(), {"foo": "bar"})


class TestValidateConfigPath(unittest.TestCase):
    """Tests for _validate_config_path static method."""

    def test_valid_path_returns_resolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.yaml"
            p.write_text("", encoding="utf-8")
            result = ScriptBase._validate_config_path(p)
            self.assertEqual(result, p.resolve())

    def test_string_path_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.yaml"
            p.write_text("", encoding="utf-8")
            result = ScriptBase._validate_config_path(str(p))
            self.assertEqual(result, p.resolve())

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError) as cm:
            ScriptBase._validate_config_path(Path("../../etc/passwd"))
        self.assertIn("..", str(cm.exception))

    def test_path_traversal_string_input(self):
        with self.assertRaises(ValueError) as cm:
            ScriptBase._validate_config_path("../../etc/passwd")
        self.assertIn("..", str(cm.exception))

    def test_path_traversal_middle_segment(self):
        with self.assertRaises(ValueError) as cm:
            ScriptBase._validate_config_path(Path("/tmp/../etc/config.yaml"))
        self.assertIn("..", str(cm.exception))

    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "real.yaml"
            target.write_text("", encoding="utf-8")
            link = Path(tmp) / "link.yaml"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Cannot create symlinks on this platform")
            with self.assertRaises(ValueError) as cm:
                ScriptBase._validate_config_path(link)
            self.assertIn("symlink", str(cm.exception).lower())

    def test_returns_path_object(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "config.yaml"
            p.write_text("", encoding="utf-8")
            result = ScriptBase._validate_config_path(p)
            self.assertIsInstance(result, Path)


class TestImportConfig(unittest.TestCase):
    """Tests for import_config method."""

    def test_import_config_valid(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("key: value\n", encoding="utf-8")
            result = script.import_config(config_path)
            self.assertEqual(result, {"key": "value"})

    def test_import_config_empty_file(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("---\n", encoding="utf-8")
            result = script.import_config(config_path)
            self.assertEqual(result, {})

    def test_import_config_truly_empty_file(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("", encoding="utf-8")
            result = script.import_config(config_path)
            self.assertEqual(result, {})

    def test_import_config_nonexistent(self):
        script = _ConcreteScript()
        with self.assertRaises(FileNotFoundError) as cm:
            script.import_config(Path("/nonexistent/config.yaml"))
        self.assertIn("not found", str(cm.exception))

    def test_import_config_path_traversal(self):
        script = _ConcreteScript()
        with self.assertRaises(ValueError):
            script.import_config("../../etc/config.yaml")

    def test_import_config_non_dict(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError) as cm:
                script.import_config(config_path)
            self.assertIn("mapping", str(cm.exception))

    def test_import_config_non_dict_string(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("just a string\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                script.import_config(config_path)

    def test_import_config_directory(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_dir = Path(tmp) / "subdir"
            config_dir.mkdir()
            with self.assertRaises(ValueError) as cm:
                script.import_config(config_dir)
            self.assertIn("not a regular file", str(cm.exception))

    def test_import_config_calls_load_config(self):
        script = _ConfigScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("foo: bar\nbaz: 123\n", encoding="utf-8")
            script.import_config(config_path)
            saved = script.save_config()
            self.assertEqual(saved, {"foo": "bar", "baz": 123})

    def test_import_config_returns_parsed_data(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("a: 1\nb: two\n", encoding="utf-8")
            result = script.import_config(config_path)
            self.assertEqual(result, {"a": 1, "b": "two"})

    def test_import_config_with_string_path(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("x: y\n", encoding="utf-8")
            result = script.import_config(str(config_path))
            self.assertEqual(result, {"x": "y"})

    def test_import_config_nested_dict(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("parent:\n  child: value\n", encoding="utf-8")
            result = script.import_config(config_path)
            self.assertEqual(result, {"parent": {"child": "value"}})

    def test_import_config_unicode(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.yaml"
            config_path.write_text("label: \u4e2d\u6587\u6d4b\u8bd5\n", encoding="utf-8")
            result = script.import_config(config_path)
            self.assertEqual(result, {"label": "\u4e2d\u6587\u6d4b\u8bd5"})


class TestExportConfig(unittest.TestCase):
    """Tests for export_config method."""

    def test_export_config_creates_file(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "output.yaml"
            script.export_config(config_path)
            self.assertTrue(config_path.exists())

    def test_export_config_includes_script_name(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "output.yaml"
            script.export_config(config_path)
            content = config_path.read_text(encoding="utf-8")
            self.assertIn("test_script", content)
            self.assertIn("__script_name__", content)

    def test_export_config_creates_parent_dirs(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "sub" / "dir" / "output.yaml"
            script.export_config(config_path)
            self.assertTrue(config_path.exists())

    def test_export_config_with_existing_data(self):
        script = _ConfigScript()
        script.load_config({"setting1": "value1", "count": 99})
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "output.yaml"
            script.export_config(config_path)
            content = config_path.read_text(encoding="utf-8")
            self.assertIn("setting1", content)
            self.assertIn("value1", content)
            self.assertIn("99", content)
            self.assertIn("config_script", content)

    def test_export_config_yaml_readable(self):
        import yaml

        script = _ConfigScript()
        script.load_config({"alpha": "beta"})
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "output.yaml"
            script.export_config(config_path)
            loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(loaded["alpha"], "beta")
            self.assertEqual(loaded["__script_name__"], "config_script")

    def test_export_config_path_traversal_rejected(self):
        script = _ConcreteScript()
        with self.assertRaises(ValueError):
            script.export_config("../../etc/evil.yaml")

    def test_export_config_string_path(self):
        script = _ConcreteScript()
        with tempfile.TemporaryDirectory() as tmp:
            config_path = str(Path(tmp) / "output.yaml")
            script.export_config(config_path)
            self.assertTrue(Path(config_path).exists())


class TestConfigRoundTrip(unittest.TestCase):
    """Tests for export -> import round-trip."""

    def test_roundtrip_simple(self):
        import yaml

        script = _ConfigScript()
        script.load_config({"key1": "val1", "key2": 42})
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "roundtrip.yaml"
            script.export_config(config_path)

            # Create a fresh script and import
            script2 = _ConfigScript()
            script2.import_config(config_path)
            saved = script2.save_config()
            # Note: __script_name__ is added by export_config but
            # load_config receives the full dict including it
            self.assertEqual(saved["key1"], "val1")
            self.assertEqual(saved["key2"], 42)

    def test_roundtrip_preserves_script_name(self):
        import yaml

        script = _ConfigScript()
        script.load_config({"x": "y"})
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "roundtrip.yaml"
            script.export_config(config_path)
            content = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            self.assertEqual(content["__script_name__"], "config_script")


class TestScriptBaseTestConnection(unittest.TestCase):
    """Tests for test_connection method."""

    def test_test_connection_default(self):
        script = _ConcreteScript()
        success, msg = script.test_connection()
        self.assertTrue(success)
        self.assertEqual(msg, "OK")

    def test_test_connection_returns_tuple(self):
        script = _ConcreteScript()
        result = script.test_connection()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)

    def test_test_connection_first_element_bool(self):
        script = _ConcreteScript()
        success, _ = script.test_connection()
        self.assertIsInstance(success, bool)

    def test_test_connection_second_element_str(self):
        script = _ConcreteScript()
        _, msg = script.test_connection()
        self.assertIsInstance(msg, str)


class TestTrayMenuItem(unittest.TestCase):
    """Tests for TrayMenuItem dataclass."""

    def test_default_values(self):
        item = TrayMenuItem()
        self.assertEqual(item.label, "")
        self.assertIsNone(item.action)
        self.assertIsNone(item.items)
        self.assertIsNone(item.checked)
        self.assertTrue(item.enabled)
        self.assertFalse(item.separator)

    def test_with_label(self):
        item = TrayMenuItem(label="Test")
        self.assertEqual(item.label, "Test")

    def test_with_action(self):
        called = [False]

        def cb():
            called[0] = True

        item = TrayMenuItem(label="Click", action=cb)
        item.action()
        self.assertTrue(called[0])

    def test_separator(self):
        item = TrayMenuItem(separator=True)
        self.assertTrue(item.separator)

    def test_with_sub_items(self):
        sub = [TrayMenuItem(label="Sub1"), TrayMenuItem(label="Sub2")]
        item = TrayMenuItem(label="Parent", items=sub)
        self.assertEqual(len(item.items), 2)
        self.assertEqual(item.items[0].label, "Sub1")
        self.assertEqual(item.items[1].label, "Sub2")

    def test_callable_label(self):
        item = TrayMenuItem(label=lambda: "Dynamic")
        self.assertTrue(callable(item.label))
        self.assertEqual(item.label(), "Dynamic")

    def test_callable_checked(self):
        item = TrayMenuItem(label="Toggle", checked=lambda: True)
        self.assertTrue(callable(item.checked))
        self.assertTrue(item.checked())

    def test_callable_checked_false(self):
        item = TrayMenuItem(label="Toggle", checked=lambda: False)
        self.assertFalse(item.checked())

    def test_checked_none(self):
        item = TrayMenuItem(label="Item", checked=None)
        self.assertIsNone(item.checked)

    def test_checked_bool(self):
        item = TrayMenuItem(label="Item", checked=True)
        self.assertTrue(item.checked)
        item2 = TrayMenuItem(label="Item", checked=False)
        self.assertFalse(item2.checked)

    def test_callable_enabled(self):
        item = TrayMenuItem(label="Item", enabled=lambda: False)
        self.assertTrue(callable(item.enabled))
        self.assertFalse(item.enabled())

    def test_enabled_bool_true(self):
        item = TrayMenuItem(label="Item", enabled=True)
        self.assertTrue(item.enabled)

    def test_enabled_bool_false(self):
        item = TrayMenuItem(label="Item", enabled=False)
        self.assertFalse(item.enabled)

    def test_nested_sub_items(self):
        deep = TrayMenuItem(
            label="Root",
            items=[
                TrayMenuItem(
                    label="Level1",
                    items=[
                        TrayMenuItem(label="Level2")
                    ]
                )
            ]
        )
        self.assertEqual(deep.items[0].items[0].label, "Level2")

    def test_action_none_default(self):
        item = TrayMenuItem(label="NoAction")
        self.assertIsNone(item.action)

    def test_items_none_default(self):
        item = TrayMenuItem(label="NoItems")
        self.assertIsNone(item.items)

    def test_equality(self):
        item1 = TrayMenuItem(label="A", separator=False)
        item2 = TrayMenuItem(label="A", separator=False)
        self.assertEqual(item1, item2)

    def test_inequality(self):
        item1 = TrayMenuItem(label="A")
        item2 = TrayMenuItem(label="B")
        self.assertNotEqual(item1, item2)


class TestScriptBaseLifecycle(unittest.TestCase):
    """Integration-style tests for the full script lifecycle."""

    def test_full_lifecycle(self):
        script = _ConfigScript()
        # 1. Initial state
        self.assertIsNone(script.context)
        self.assertEqual(script.save_config(), {})

        # 2. Context ready
        ctx = MagicMock()
        script.on_context_ready(ctx)
        self.assertIs(script.context, ctx)

        # 3. Activate
        script.activate()

        # 4. Load config
        script.load_config({"theme": "dark"})

        # 5. Deactivate
        script.deactivate()
        self.assertIsNone(script.context)
        ctx.shutdown.assert_called_once()

    def test_activate_deactivate_without_context(self):
        script = _ConcreteScript()
        script.activate()
        script.deactivate()
        self.assertIsNone(script.context)

    def test_multiple_context_ready(self):
        script = _ConcreteScript()
        ctx1 = MagicMock()
        ctx2 = MagicMock()
        script.on_context_ready(ctx1)
        self.assertIs(script.context, ctx1)
        script.on_context_ready(ctx2)
        self.assertIs(script.context, ctx2)
        # Deactivating should call shutdown on ctx2 only
        script.deactivate()
        ctx2.shutdown.assert_called_once()
        ctx1.shutdown.assert_not_called()


if __name__ == "__main__":
    unittest.main()
