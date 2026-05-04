from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from platex_client.loader import (
    LegacyProcessor,
    OcrProcessorAdapter,
    load_script_processor,
)
from platex_client.script_base import ScriptBase
from platex_client.script_safety import _SCRIPT_SAFETY_ENV


class _FakeScriptBase(ScriptBase):
    """Concrete ScriptBase for testing OcrProcessorAdapter."""

    def __init__(self, name="fake", display_name="Fake", description="Fake script"):
        self._name = name
        self._display_name = display_name
        self._description = description

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
        return True

    def process_image(self, image_bytes, context=None):
        return "x^2 + y^2"


# ---------------------------------------------------------------------------
# load_script_processor tests
# ---------------------------------------------------------------------------


class TestLoadScriptProcessorWithCreateScript(unittest.TestCase):
    """Tests for load_script_processor when the script defines create_script()."""

    def test_returns_ocr_processor_adapter(self):
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
                "    def description(self): return 'Test script'\n"
                "    def has_ocr_capability(self): return True\n"
                "    def process_image(self, image_bytes, context=None): return 'result'\n"
                "def create_script(): return MyScript()\n",
                encoding="utf-8",
            )
            result = load_script_processor(script_path)
            self.assertIsInstance(result, OcrProcessorAdapter)

    def test_create_script_takes_precedence_over_process_image(self):
        """If both create_script and process_image exist, create_script wins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "both.py"
            script_path.write_text(
                "from platex_client.script_base import ScriptBase\n"
                "class MyScript(ScriptBase):\n"
                "    @property\n"
                "    def name(self): return 'my_script'\n"
                "    @property\n"
                "    def display_name(self): return 'My Script'\n"
                "    @property\n"
                "    def description(self): return 'Test script'\n"
                "    def has_ocr_capability(self): return True\n"
                "    def process_image(self, image_bytes, context=None): return 'from_class'\n"
                "def create_script(): return MyScript()\n"
                "def process_image(image_bytes, context=None): return 'from_module'\n",
                encoding="utf-8",
            )
            result = load_script_processor(script_path)
            self.assertIsInstance(result, OcrProcessorAdapter)
            self.assertEqual(result.process_image(b""), "from_class")

    def test_create_script_returns_non_scriptbase_falls_back(self):
        """If create_script returns a non-ScriptBase, fall back to process_image."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "bad_create.py"
            script_path.write_text(
                "def create_script(): return 42\n"
                "def process_image(image_bytes, context=None): return 'legacy_result'\n",
                encoding="utf-8",
            )
            result = load_script_processor(script_path)
            self.assertIsInstance(result, LegacyProcessor)

    def test_create_script_returns_none_falls_back(self):
        """If create_script returns None, fall back to process_image."""
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "none_create.py"
            script_path.write_text(
                "def create_script(): return None\n"
                "def process_image(image_bytes, context=None): return 'legacy_result'\n",
                encoding="utf-8",
            )
            result = load_script_processor(script_path)
            self.assertIsInstance(result, LegacyProcessor)


class TestLoadScriptProcessorWithProcessImage(unittest.TestCase):
    """Tests for load_script_processor when the script defines process_image()."""

    def test_returns_legacy_processor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "legacy.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            result = load_script_processor(script_path)
            self.assertIsInstance(result, LegacyProcessor)

    def test_legacy_processor_process_image_delegates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "legacy2.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'hello world'\n",
                encoding="utf-8",
            )
            result = load_script_processor(script_path)
            self.assertEqual(result.process_image(b"test"), "hello world")


class TestLoadScriptProcessorWithNeither(unittest.TestCase):
    """Tests for load_script_processor when the script has neither entry point."""

    def test_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "neither.py"
            script_path.write_text("x = 42\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                load_script_processor(script_path)
            self.assertIn("neither create_script() nor process_image()", str(ctx.exception))


class TestLoadScriptProcessorWithSyntaxError(unittest.TestCase):
    """Tests for load_script_processor when the script has a syntax error."""

    def test_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "syntax_err.py"
            script_path.write_text("def foo(\n", encoding="utf-8")
            with self.assertRaises(RuntimeError) as ctx:
                load_script_processor(script_path)
            self.assertIn("Failed to execute script", str(ctx.exception))


class TestLoadScriptProcessorWithRuntimeError(unittest.TestCase):
    """Tests for load_script_processor when the script raises at import time."""

    def test_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "runtime_err.py"
            script_path.write_text(
                "raise RuntimeError('boom')\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError) as ctx:
                load_script_processor(script_path)
            self.assertIn("Failed to execute script", str(ctx.exception))


class TestLoadScriptProcessorWithImportError(unittest.TestCase):
    """Tests for load_script_processor when the script has an import error."""

    def test_raises_runtime_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "import_err.py"
            script_path.write_text(
                "import nonexistent_module_xyz_12345\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_script_processor(script_path)


class TestLoadScriptProcessorPathValidation(unittest.TestCase):
    """Tests for load_script_processor path validation."""

    def test_nonexistent_path_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            load_script_processor(Path("/nonexistent/path/script.py"))

    def test_empty_file_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "empty.py"
            script_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_script_processor(script_path)


class TestLoadScriptProcessorDangerousPatterns(unittest.TestCase):
    """Tests for load_script_processor blocking dangerous code."""

    def test_blocked_pattern_raises_value_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dangerous.py"
            script_path.write_text(
                "import os\n"
                "os.system('echo hello')\n"
                "def process_image(image_bytes, context=None): return 'x'\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as ctx:
                load_script_processor(script_path)
            self.assertIn("blocked", str(ctx.exception).lower())

    def test_blocked_pattern_allowed_with_env_var(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dangerous_allowed.py"
            script_path.write_text(
                "import os\n"
                "os.system('echo hello')\n"
                "def process_image(image_bytes, context=None): return 'x'\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {_SCRIPT_SAFETY_ENV: "1"}):
                result = load_script_processor(script_path)
                self.assertIsInstance(result, LegacyProcessor)


# ---------------------------------------------------------------------------
# OcrProcessorAdapter tests
# ---------------------------------------------------------------------------


class TestOcrProcessorAdapter(unittest.TestCase):
    """Tests for OcrProcessorAdapter delegation."""

    def test_delegates_process_image(self):
        script = _FakeScriptBase()
        adapter = OcrProcessorAdapter(script)
        result = adapter.process_image(b"image_data")
        self.assertEqual(result, "x^2 + y^2")

    def test_delegates_with_context(self):
        script = _FakeScriptBase()
        adapter = OcrProcessorAdapter(script)
        result = adapter.process_image(b"image_data", context={"key": "value"})
        self.assertEqual(result, "x^2 + y^2")

    def test_holds_reference_to_script(self):
        script = _FakeScriptBase()
        adapter = OcrProcessorAdapter(script)
        self.assertIs(adapter._script, script)

    def test_is_instance_of_ocr_processor(self):
        from platex_client.models import OcrProcessor

        script = _FakeScriptBase()
        adapter = OcrProcessorAdapter(script)
        self.assertIsInstance(adapter, OcrProcessor)

    def test_process_image_propagates_exception(self):
        class _BrokenScript(ScriptBase):
            @property
            def name(self): return "broken"
            @property
            def display_name(self): return "Broken"
            @property
            def description(self): return "Broken script"
            def process_image(self, image_bytes, context=None):
                raise ValueError("script error")

        adapter = OcrProcessorAdapter(_BrokenScript())
        with self.assertRaises(ValueError):
            adapter.process_image(b"data")


# ---------------------------------------------------------------------------
# LegacyProcessor tests
# ---------------------------------------------------------------------------


class TestLegacyProcessorWithStringReturn(unittest.TestCase):
    """Tests for LegacyProcessor when process_image returns a string."""

    def test_string_return(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "str_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'E = mc^2'\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            result = processor.process_image(b"img")
            self.assertEqual(result, "E = mc^2")


class TestLegacyProcessorWithDictReturn(unittest.TestCase):
    """Tests for LegacyProcessor when process_image returns a dict with 'latex'."""

    def test_dict_return(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dict_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n"
                "    return {'latex': 'a^2 + b^2'}\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            result = processor.process_image(b"img")
            self.assertEqual(result, "a^2 + b^2")

    def test_dict_return_converts_latex_to_string(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dict_int.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n"
                "    return {'latex': 42}\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            result = processor.process_image(b"img")
            self.assertEqual(result, "42")


class TestLegacyProcessorWithUnsupportedType(unittest.TestCase):
    """Tests for LegacyProcessor when process_image returns an unsupported type."""

    def test_list_return_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "list_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return [1, 2, 3]\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError) as ctx:
                processor.process_image(b"img")
            self.assertIn("unsupported result", str(ctx.exception))

    def test_int_return_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "int_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 42\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError):
                processor.process_image(b"img")

    def test_none_return_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "none_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return None\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError):
                processor.process_image(b"img")

    def test_dict_without_latex_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "no_latex.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n"
                "    return {'text': 'hello'}\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError):
                processor.process_image(b"img")


class TestLegacyProcessorWithEmptyStringReturn(unittest.TestCase):
    """Tests for LegacyProcessor when process_image returns an empty string."""

    def test_empty_string_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "empty_str.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return ''\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError) as ctx:
                processor.process_image(b"img")
            self.assertIn("empty LaTeX", str(ctx.exception))


class TestLegacyProcessorWithWhitespaceOnlyReturn(unittest.TestCase):
    """Tests for LegacyProcessor when process_image returns whitespace-only string."""

    def test_whitespace_only_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ws_str.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return '   \\n\\t  '\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError) as ctx:
                processor.process_image(b"img")
            self.assertIn("empty LaTeX", str(ctx.exception))


class TestLegacyProcessorProcessImageMissing(unittest.TestCase):
    """Tests for LegacyProcessor when process_image is removed from module."""

    def test_missing_process_image_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "missing_pi.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'ok'\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            # Remove process_image from the module to simulate missing function
            del processor._module.process_image
            with self.assertRaises(RuntimeError) as ctx:
                processor.process_image(b"img")
            self.assertIn("does not define process_image", str(ctx.exception))


class TestLegacyProcessorIsOcrProcessor(unittest.TestCase):
    """Tests that LegacyProcessor is an instance of OcrProcessor."""

    def test_is_instance(self):
        from platex_client.models import OcrProcessor

        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ocr.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x'\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            self.assertIsInstance(processor, OcrProcessor)


class TestLegacyProcessorContext(unittest.TestCase):
    """Tests for LegacyProcessor context parameter handling."""

    def test_context_defaults_to_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ctx.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n"
                "    assert context is not None, 'context should default to {}'\n"
                "    return 'ok'\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            result = processor.process_image(b"img")
            self.assertEqual(result, "ok")

    def test_context_passed_through(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ctx2.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n"
                "    return context.get('key', 'missing')\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            # The result goes through _extract_legacy_result which expects str/dict
            # This will fail because 'missing' is a valid string
            result = processor.process_image(b"img", context={"key": "found"})
            self.assertEqual(result, "found")


if __name__ == "__main__":
    unittest.main()
