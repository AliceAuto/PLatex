from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from platex_client.script_safety import (
    check_blocked_patterns,
    scan_script_source,
    validate_script_path,
)


class TestScanScriptSource(unittest.TestCase):
    def test_safe_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "safe_script.py"
            script_path.write_text(
                "import json\nimport math\n\ndef process():\n    return 'ok'\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertEqual(len(blocked), 0)

    def test_dangerous_os_system(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dangerous.py"
            script_path.write_text(
                'import os\nos.system("rm -rf /")\n',
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("os.system", blocked)

    def test_dangerous_subprocess(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "dangerous2.py"
            script_path.write_text(
                'import subprocess\nsubprocess.call(["rm", "-rf", "/"])\n',
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("subprocess execution", blocked)

    def test_dangerous_eval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "eval_script.py"
            script_path.write_text(
                "eval('__import__(\"os\").system(\"ls\")')\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("eval()", blocked)

    def test_dangerous_exec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "exec_script.py"
            script_path.write_text(
                'exec("import os")\n',
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("exec()", blocked)

    def test_empty_script(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "empty.py"
            script_path.write_text("", encoding="utf-8")
            warnings, blocked = scan_script_source(script_path)
            self.assertEqual(len(warnings), 0)
            self.assertEqual(len(blocked), 0)

    def test_nonexistent_script(self):
        warnings, blocked = scan_script_source(Path("/nonexistent/script.py"))
        self.assertEqual(len(warnings), 0)
        self.assertEqual(len(blocked), 0)

    def test_safe_imports_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "safe.py"
            script_path.write_text(
                "import json\nimport math\nimport re\n\ndef process():\n    return json.dumps({'a': 1})\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertEqual(len(blocked), 0)

    def test_dangerous_shutil(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "shutil_script.py"
            script_path.write_text(
                "import shutil\nshutil.rmtree('/')\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("shutil.rmtree", warnings)

    def test_dangerous_socket(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "socket_script.py"
            script_path.write_text(
                "import socket\ns = socket.socket()\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("socket access", warnings)

    def test_dangerous_pickle(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "pickle_script.py"
            script_path.write_text(
                "import pickle\npickle.loads(b'')\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("pickle deserialization", blocked)

    def test_dangerous_os_environ(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "environ_script.py"
            script_path.write_text(
                "import os\nval = os.environ.get('KEY')\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("os.environ access", warnings)

    def test_dangerous_webbrowser(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "web_script.py"
            script_path.write_text(
                "import webbrowser\nwebbrowser.open('http://example.com')\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("webbrowser access", warnings)

    def test_dangerous_ctypes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "ctypes_script.py"
            script_path.write_text(
                "import ctypes\nctypes.windll.kernel32\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertIn("ctypes FFI access", warnings)


class TestCheckBlockedPatterns(unittest.TestCase):
    def test_no_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "safe.py"
            script_path.write_text("x = 1\n", encoding="utf-8")
            result = check_blocked_patterns(script_path)
            self.assertEqual(len(result), 0)

    def test_blocked_os_system(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "blocked.py"
            script_path.write_text('os.system("ls")\n', encoding="utf-8")
            result = check_blocked_patterns(script_path)
            self.assertIn("os.system", result)

    def test_blocked_eval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "blocked.py"
            script_path.write_text('eval("1+1")\n', encoding="utf-8")
            result = check_blocked_patterns(script_path)
            self.assertIn("eval()", result)

    def test_nonexistent_file(self):
        result = check_blocked_patterns(Path("/nonexistent/script.py"))
        self.assertEqual(len(result), 0)


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

    def test_very_large_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            script_path = Path(tmpdir) / "large.py"
            script_path.write_text("x = 1\n" * 500000, encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(script_path)


if __name__ == "__main__":
    unittest.main()
