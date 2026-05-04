from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from platex_client.script_safety import (
    _check_dangerous_patterns,
    _extract_legacy_result,
    _load_script_module,
    check_blocked_patterns,
    scan_script_source,
    validate_script_path,
)


class TestScanScriptSourceDangerousPatterns(unittest.TestCase):
    def _write_script(self, content, temp_dir):
        script_path = Path(temp_dir) / "test_script.py"
        script_path.write_text(content, encoding="utf-8")
        return script_path

    def test_os_system_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import os\nos.system('echo hi')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("os.system", warnings)

    def test_subprocess_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import subprocess\nsubprocess.run(['ls'])\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("subprocess execution", warnings)

    def test_exec_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "exec('print(1)')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("exec()", blocked)

    def test_eval_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "eval('1+1')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("eval()", blocked)

    def test_import_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "__import__('os')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("__import__()", blocked)

    def test_socket_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import socket\nsocket.socket()\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("socket access", warnings)

    def test_pickle_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import pickle\npickle.loads(b'')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("pickle deserialization", blocked)

    def test_requests_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import requests\nrequests.get('http://example.com')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("requests HTTP call", warnings)

    def test_os_environ_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import os\nx = os.environ\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("os.environ access", warnings)

    def test_ctypes_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import ctypes\nctypes.windll.kernel32\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("ctypes FFI access", warnings)

    def test_safe_script_no_warnings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "def process_image(image_bytes, context):\n    return 'safe result'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertEqual(len(warnings), 0)
            self.assertEqual(len(blocked), 0)

    def test_shutil_rmtree_warning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import shutil\nshutil.rmtree('/tmp/x')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("shutil.rmtree", warnings)

    def test_compile_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "compile('1+1', '<string>', 'eval')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("compile()", blocked)

    def test_builtins_access_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "x = __builtins__\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("__builtins__ access", blocked)

    def test_os_popen_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self._write_script(
                "import os\nos.popen('ls')\ndef process_image(i,c): return 't'\n",
                temp_dir,
            )
            warnings, blocked = scan_script_source(path)
            self.assertIn("os.popen()", blocked)


class TestExtractLegacyResult(unittest.TestCase):
    def test_string_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return r'x^2'\n",
                encoding="utf-8",
            )
            module = _load_script_module(script_path)
            result = _extract_legacy_result(module, script_path, "x^2")
            self.assertEqual(result, "x^2")

    def test_dict_result_with_latex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return {'latex': 'x^2'}\n",
                encoding="utf-8",
            )
            module = _load_script_module(script_path)
            result = _extract_legacy_result(module, script_path, {"latex": "x^2"})
            self.assertEqual(result, "x^2")

    def test_unsupported_result_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, 42)

    def test_empty_string_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, "")

    def test_whitespace_only_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, "   ")

    def test_dict_without_latex_key(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            with self.assertRaises(RuntimeError):
                _extract_legacy_result(module, script_path, {"text": "x^2"})

    def test_string_result_stripped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            module = _load_script_module(script_path)
            result = _extract_legacy_result(module, script_path, "  x^2  ")
            self.assertEqual(result, "x^2")


class TestValidateScriptPathEdgeCases(unittest.TestCase):
    def test_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "real.py"
            target.write_text("def process_image(i,c): return 't'\n", encoding="utf-8")
            link = Path(temp_dir) / "link.py"
            try:
                link.symlink_to(target)
            except OSError:
                self.skipTest("Cannot create symlinks on this system")
            with self.assertRaises(ValueError):
                validate_script_path(link)

    def test_path_traversal_rejected(self):
        with self.assertRaises((ValueError, FileNotFoundError)):
            validate_script_path(Path("../../etc/script.py"))


class TestCheckBlockedPatterns(unittest.TestCase):
    def test_no_blocked_patterns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "safe.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'safe'\n",
                encoding="utf-8",
            )
            blocked = check_blocked_patterns(script_path)
            self.assertEqual(len(blocked), 0)

    def test_exec_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "evil.py"
            script_path.write_text(
                "exec('print(1)')\ndef process_image(i,c): return 't'\n",
                encoding="utf-8",
            )
            blocked = check_blocked_patterns(script_path)
            self.assertIn("exec()", blocked)


if __name__ == "__main__":
    unittest.main()
