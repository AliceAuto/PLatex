from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from platex_client.loader import load_script_processor
from platex_client.script_safety import validate_script_path


class TestLoadScriptProcessor(unittest.TestCase):
    def test_load_nonexistent_path(self):
        with self.assertRaises(FileNotFoundError):
            load_script_processor(Path("/nonexistent/script.py"))

    def test_load_invalid_python(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "bad_script.py"
            script_path.write_text("this is not valid python {{{", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_script_processor(script_path)

    def test_load_script_no_processor(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "no_processor.py"
            script_path.write_text("x = 42\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_script_processor(script_path)

    def test_load_empty_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "empty.py"
            script_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_script_processor(script_path)

    def test_load_script_with_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "syntax_error.py"
            script_path.write_text("def foo(\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_script_processor(script_path)

    def test_load_script_with_import_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "import_error.py"
            script_path.write_text(
                "import nonexistent_module_xyz\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                load_script_processor(script_path)

    def test_load_script_with_process_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ocr_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context=None):\n    return 'x^2'\n",
                encoding="utf-8",
            )
            result = load_script_processor(script_path)
            self.assertIsNotNone(result)

    def test_load_script_with_create_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "new_script.py"
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
            result = load_script_processor(script_path)
            self.assertIsNotNone(result)


class TestValidateScriptPath(unittest.TestCase):
    def test_nonexistent_path(self):
        with self.assertRaises(FileNotFoundError):
            validate_script_path(Path("/nonexistent/script.py"))

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "empty.py"
            script_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(script_path)

    def test_path_traversal(self):
        with self.assertRaises(ValueError):
            validate_script_path(Path("../../etc/passwd"))

    def test_valid_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "valid.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            validate_script_path(script_path)


if __name__ == "__main__":
    unittest.main()
