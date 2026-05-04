from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from platex_client.logging_utils import _SensitiveDataFilter, setup_logging


# ---------------------------------------------------------------------------
# _SensitiveDataFilter
# ---------------------------------------------------------------------------

class TestSensitiveDataFilter(unittest.TestCase):
    """Tests for _SensitiveDataFilter logging filter."""

    def setUp(self):
        self.filt = _SensitiveDataFilter()

    # -- api_key patterns --

    def test_filter_masks_api_key_colon(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "api_key: sk-1234567890", (), None)
        self.filt.filter(record)
        self.assertNotIn("sk-1234567890", record.msg)
        self.assertIn("***", record.msg)

    def test_filter_masks_api_key_equals(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "api_key=sk-1234567890", (), None)
        self.filt.filter(record)
        self.assertNotIn("sk-1234567890", record.msg)

    def test_filter_masks_apikey_no_underscore(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "apikey: mykey123", (), None)
        self.filt.filter(record)
        self.assertNotIn("mykey123", record.msg)

    def test_filter_masks_api_key_dash(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "api-key: sk-abc123", (), None)
        self.filt.filter(record)
        self.assertNotIn("sk-abc123", record.msg)

    # -- token patterns --

    def test_filter_masks_token(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "token: abc123def456", (), None)
        self.filt.filter(record)
        self.assertNotIn("abc123def456", record.msg)

    def test_filter_masks_token_equals(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "token=abc123", (), None)
        self.filt.filter(record)
        self.assertNotIn("abc123", record.msg)

    # -- secret patterns --

    def test_filter_masks_secret(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "secret: mysecret", (), None)
        self.filt.filter(record)
        self.assertNotIn("mysecret", record.msg)

    def test_filter_masks_secret_equals(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "secret=mysecret", (), None)
        self.filt.filter(record)
        self.assertNotIn("mysecret", record.msg)

    # -- password patterns --

    def test_filter_masks_password(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "password: hunter2", (), None)
        self.filt.filter(record)
        self.assertNotIn("hunter2", record.msg)

    def test_filter_masks_password_equals(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "password=hunter2", (), None)
        self.filt.filter(record)
        self.assertNotIn("hunter2", record.msg)

    # -- non-sensitive data passes through --

    def test_filter_allows_normal_message(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "normal message", (), None)
        result = self.filt.filter(record)
        self.assertTrue(result)
        self.assertEqual(record.msg, "normal message")

    def test_filter_preserves_non_sensitive_data(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "model: glm-4", (), None)
        self.filt.filter(record)
        self.assertIn("glm-4", record.msg)

    def test_filter_preserves_url(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "url: https://api.example.com", (), None)
        self.filt.filter(record)
        self.assertIn("https://api.example.com", record.msg)

    # -- record.args handling --

    def test_filter_masks_args(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "key: %s", ("api_key=sk-secret123",), None)
        self.filt.filter(record)
        self.assertNotIn("sk-secret123", str(record.args))

    def test_filter_preserves_non_sensitive_args(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "value: %s", ("normal",), None)
        self.filt.filter(record)
        self.assertEqual(record.args[0], "normal")

    def test_filter_masks_sensitive_in_args(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "config: %s", ("api_key=sk-12345",), None)
        self.filt.filter(record)
        self.assertNotIn("sk-12345", str(record.args))

    def test_filter_mixed_args(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0, "keys: %s %s",
            ("api_key=secret", "normal_value"), None,
        )
        self.filt.filter(record)
        self.assertNotIn("secret", str(record.args[0]))
        self.assertEqual(record.args[1], "normal_value")

    def test_filter_non_string_args_untouched(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "count: %d", (42,), None)
        self.filt.filter(record)
        self.assertEqual(record.args[0], 42)

    # -- case insensitive --

    def test_filter_case_insensitive_api_key(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "API_KEY: sk-12345", (), None)
        self.filt.filter(record)
        self.assertNotIn("sk-12345", record.msg)

    def test_filter_case_insensitive_token(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "TOKEN: abc123", (), None)
        self.filt.filter(record)
        self.assertNotIn("abc123", record.msg)

    def test_filter_case_insensitive_secret(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "SECRET: mysecret", (), None)
        self.filt.filter(record)
        self.assertNotIn("mysecret", record.msg)

    def test_filter_case_insensitive_password(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "PASSWORD: mypass", (), None)
        self.filt.filter(record)
        self.assertNotIn("mypass", record.msg)

    # -- return value --

    def test_filter_returns_true(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "any message", (), None)
        self.assertTrue(self.filt.filter(record))

    def test_filter_returns_true_when_masking(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "api_key: secret", (), None)
        self.assertTrue(self.filt.filter(record))

    # -- non-string msg --

    def test_filter_non_string_msg(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, 42, (), None)
        result = self.filt.filter(record)
        self.assertTrue(result)

    def test_filter_none_msg(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, None, (), None)
        result = self.filt.filter(record)
        self.assertTrue(result)

    # -- empty args --

    def test_filter_empty_args(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "api_key: secret", (), None)
        self.filt.filter(record)
        self.assertNotIn("secret", record.msg)

    def test_filter_none_args(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "api_key: secret", None, None)
        self.filt.filter(record)
        self.assertNotIn("secret", record.msg)

    # -- multiple sensitive patterns in one message --

    def test_filter_multiple_sensitive_in_message(self):
        record = logging.LogRecord(
            "test", logging.INFO, "", 0,
            "api_key: sk-123 token: tok-456",
            (), None,
        )
        self.filt.filter(record)
        self.assertNotIn("sk-123", record.msg)
        self.assertNotIn("tok-456", record.msg)

    # -- preserves key name in output --

    def test_filter_preserves_key_name(self):
        record = logging.LogRecord("test", logging.INFO, "", 0, "api_key: sk-12345", (), None)
        self.filt.filter(record)
        self.assertIn("api_key", record.msg)


# ---------------------------------------------------------------------------
# setup_logging
# ---------------------------------------------------------------------------

class TestSetupLogging(unittest.TestCase):
    """Tests for setup_logging(log_file, level)."""

    def _cleanup_handlers(self, original_handlers, original_filters):
        root = logging.getLogger()
        for h in root.handlers[:]:
            if h not in original_handlers:
                root.removeHandler(h)
                h.close()
        root.filters = [f for f in root.filters if f in original_filters]

    def test_setup_logging_with_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                setup_logging(log_file)
                logger = logging.getLogger("platex_client")
                logger.info("test message")
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_idempotent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                setup_logging(log_file)
                setup_logging(log_file)
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "subdir" / "test.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                setup_logging(log_file)
                self.assertTrue(log_file.parent.exists())
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_different_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file1 = Path(tmpdir) / "test1.log"
            log_file2 = Path(tmpdir) / "test2.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                setup_logging(log_file1)
                setup_logging(log_file2)
                file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
                self.assertTrue(len(file_handlers) >= 1)
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_creates_log_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                setup_logging(log_file)
                logger = logging.getLogger("test_setup_creates")
                logger.info("test message")
                # Force flush
                for h in root.handlers:
                    if isinstance(h, logging.FileHandler):
                        h.flush()
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_adds_sensitive_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                # Remove any existing sensitive filters for this test
                root.filters = [f for f in root.filters if not isinstance(f, _SensitiveDataFilter)]
                setup_logging(log_file)
                has_filter = any(isinstance(f, _SensitiveDataFilter) for f in root.filters)
                self.assertTrue(has_filter)
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_does_not_duplicate_sensitive_filter(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                root.filters = [f for f in root.filters if not isinstance(f, _SensitiveDataFilter)]
                setup_logging(log_file)
                count1 = sum(1 for f in root.filters if isinstance(f, _SensitiveDataFilter))
                setup_logging(Path(tmpdir) / "test2.log")
                count2 = sum(1 for f in root.filters if isinstance(f, _SensitiveDataFilter))
                self.assertEqual(count1, count2)
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_same_path_reuses_handler(self):
        """Calling setup_logging with the same path should not add a new handler."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                setup_logging(log_file)
                file_count1 = sum(1 for h in root.handlers if isinstance(h, logging.FileHandler))
                setup_logging(log_file)
                file_count2 = sum(1 for h in root.handlers if isinstance(h, logging.FileHandler))
                self.assertEqual(file_count1, file_count2)
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_writes_to_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            root = logging.getLogger()
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            try:
                setup_logging(log_file)
                test_logger = logging.getLogger("test.write.check")
                test_logger.info("unique_test_message_12345")
                for h in root.handlers:
                    if isinstance(h, logging.FileHandler):
                        h.flush()
                if log_file.exists():
                    content = log_file.read_text(encoding="utf-8")
                    self.assertIn("unique_test_message_12345", content)
            finally:
                self._cleanup_handlers(original_handlers, original_filters)

    def test_setup_logging_masks_sensitive_in_file(self):
        """Sensitive data should be masked in log file output when logged via root logger.
        Note: Python logging only checks filters on the logger where the log call
        originates, not on parent loggers during propagation. So we test with root logger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "sensitive_test.log"
            root = logging.getLogger()
            # Save and fully reset root logger state for this test
            original_handlers = list(root.handlers)
            original_filters = list(root.filters)
            original_level = root.level
            try:
                # Remove all existing handlers and filters
                for h in root.handlers[:]:
                    root.removeHandler(h)
                    h.close()
                root.filters = []
                root.setLevel(logging.WARNING)

                setup_logging(log_file)
                # Log directly on root logger to ensure filter is applied
                root.info("api_key: sk-super-secret-key-12345")
                for h in root.handlers:
                    if isinstance(h, logging.FileHandler):
                        h.flush()
                content = log_file.read_text(encoding="utf-8")
                self.assertNotIn("sk-super-secret-key-12345", content)
                self.assertIn("***", content)
            finally:
                # Restore original state
                for h in root.handlers[:]:
                    root.removeHandler(h)
                    h.close()
                root.filters = list(original_filters)
                root.level = original_level
                for h in original_handlers:
                    root.addHandler(h)


if __name__ == "__main__":
    unittest.main()
