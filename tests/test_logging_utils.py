from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from platex_client.logging_utils import _SensitiveDataFilter, setup_logging


class TestSensitiveDataFilter(unittest.TestCase):
    def setUp(self):
        self.filt = _SensitiveDataFilter()

    def test_api_key_masked_in_msg(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="api_key: sk-1234567890abcdef", args=(), exc_info=None,
        )
        self.filt.filter(record)
        self.assertNotIn("sk-1234567890abcdef", record.msg)
        self.assertIn("***", record.msg)

    def test_token_masked_in_msg(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="token: abc123def456", args=(), exc_info=None,
        )
        self.filt.filter(record)
        self.assertNotIn("abc123def456", record.msg)

    def test_secret_masked_in_msg(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="secret: mysecretvalue", args=(), exc_info=None,
        )
        self.filt.filter(record)
        self.assertNotIn("mysecretvalue", record.msg)

    def test_password_masked_in_msg(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="password: hunter2", args=(), exc_info=None,
        )
        self.filt.filter(record)
        self.assertNotIn("hunter2", record.msg)

    def test_normal_msg_unchanged(self):
        msg = "Normal log message without sensitive data"
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=msg, args=(), exc_info=None,
        )
        self.filt.filter(record)
        self.assertEqual(record.msg, msg)

    def test_args_with_sensitive_pattern_masked(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Config: %s", args=("api_key: sk-secret123",), exc_info=None,
        )
        self.filt.filter(record)
        self.assertNotIn("sk-secret123", record.args[0])

    def test_non_sensitive_args_unchanged(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="Count: %d", args=(42,), exc_info=None,
        )
        self.filt.filter(record)
        self.assertEqual(record.args, (42,))

    def test_filter_always_returns_true(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="any message", args=(), exc_info=None,
        )
        self.assertTrue(self.filt.filter(record))

    def test_case_insensitive_masking(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="API_KEY: sk-secret", args=(), exc_info=None,
        )
        self.filt.filter(record)
        self.assertNotIn("sk-secret", record.msg)

    def test_non_string_msg(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg=12345, args=(), exc_info=None,
        )
        result = self.filt.filter(record)
        self.assertTrue(result)

    def test_empty_args(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="test message", args=(), exc_info=None,
        )
        result = self.filt.filter(record)
        self.assertTrue(result)

    def test_multiple_sensitive_patterns(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="api_key: key1 token: tok2", args=(), exc_info=None,
        )
        self.filt.filter(record)
        self.assertNotIn("key1", record.msg)
        self.assertNotIn("tok2", record.msg)

    def test_api_key_with_hyphen(self):
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="api-key: sk-secret", args=(), exc_info=None,
        )
        self.filt.filter(record)
        self.assertNotIn("sk-secret", record.msg)


class TestSetupLogging(unittest.TestCase):
    def test_setup_creates_log_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "logs" / "test.log"
            setup_logging(log_file)
            self.assertTrue(log_file.parent.exists())

    def test_setup_adds_sensitive_filter(self):
        root = logging.getLogger()
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "logs" / "test.log"
            setup_logging(log_file)
            has_filter = any(isinstance(f, _SensitiveDataFilter) for f in root.filters)
            self.assertTrue(has_filter)

    def test_setup_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "logs" / "test.log"
            setup_logging(log_file)
            setup_logging(log_file)

    def test_setup_different_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file1 = Path(temp_dir) / "logs1" / "test.log"
            log_file2 = Path(temp_dir) / "logs2" / "test.log"
            setup_logging(log_file1)
            setup_logging(log_file2)

    def test_setup_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "sub" / "dir" / "test.log"
            setup_logging(log_file)
            self.assertTrue(log_file.parent.exists())


if __name__ == "__main__":
    unittest.main()
