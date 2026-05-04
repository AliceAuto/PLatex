from __future__ import annotations

import shutil
import tempfile
import threading
import time
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from platex_client.history import (
    HistoryStore,
    _MAX_FIELD_LENGTHS,
    _MAX_HISTORY_ROWS,
    _VACUUM_CHECK_INTERVAL,
    _truncate_field,
)
from platex_client.models import ClipboardEvent


class TestEnsureUtc(unittest.TestCase):
    """Tests for _ensure_utc with naive and aware datetimes."""

    def test_naive_datetime_gets_utc_tzinfo(self):
        naive = datetime(2024, 6, 15, 10, 30, 0)
        result = HistoryStore._ensure_utc(naive)
        self.assertIsNotNone(result.tzinfo)
        self.assertEqual(result.tzinfo, timezone.utc)

    def test_naive_datetime_preserves_values(self):
        naive = datetime(2024, 6, 15, 10, 30, 45, 123456)
        result = HistoryStore._ensure_utc(naive)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 6)
        self.assertEqual(result.day, 15)
        self.assertEqual(result.hour, 10)
        self.assertEqual(result.minute, 30)
        self.assertEqual(result.second, 45)

    def test_utc_aware_datetime_unchanged(self):
        aware = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        result = HistoryStore._ensure_utc(aware)
        self.assertEqual(result, aware)

    def test_non_utc_aware_datetime_converted(self):
        offset_tz = timezone(timedelta(hours=5))
        aware = datetime(2024, 6, 15, 15, 30, 0, tzinfo=offset_tz)
        result = HistoryStore._ensure_utc(aware)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.hour, 10)

    def test_negative_offset_datetime_converted(self):
        offset_tz = timezone(timedelta(hours=-8))
        aware = datetime(2024, 6, 15, 2, 0, 0, tzinfo=offset_tz)
        result = HistoryStore._ensure_utc(aware)
        self.assertEqual(result.tzinfo, timezone.utc)
        self.assertEqual(result.hour, 10)

    def test_naive_datetime_in_add_stored_as_utc(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                naive = datetime(2024, 1, 1, 12, 0, 0)
                store.add(ClipboardEvent(
                    created_at=naive,
                    image_hash="naive_utc_test",
                    image_width=100,
                    image_height=100,
                    latex="x",
                    source="test",
                    status="ok",
                    error=None,
                ))
                latest = store.latest()
                self.assertIsNotNone(latest.created_at.tzinfo)


class TestListRecentLimits(unittest.TestCase):
    """Tests for list_recent with various limit values."""

    def _make_event(self, idx=0):
        return ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash=f"hash_{idx}",
            image_width=100,
            image_height=100,
            latex=f"x^{idx}",
            source="test",
            status="ok",
            error=None,
        )

    def test_limit_one(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(5):
                    store.add(self._make_event(i))
                result = store.list_recent(limit=1)
                self.assertEqual(len(result), 1)

    def test_limit_zero_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                result = store.list_recent(limit=0)
                self.assertIsInstance(result, list)

    def test_negative_limit_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                result = store.list_recent(limit=-5)
                self.assertIsInstance(result, list)

    def test_string_limit_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                result = store.list_recent(limit="invalid")
                self.assertIsInstance(result, list)

    def test_none_limit_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                result = store.list_recent(limit=None)
                self.assertIsInstance(result, list)

    def test_very_large_limit_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                result = store.list_recent(limit=50000)
                self.assertIsInstance(result, list)
                self.assertLessEqual(len(result), HistoryStore._MAX_QUERY_LIMIT)

    def test_limit_exceeding_max_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                result = store.list_recent(limit=HistoryStore._MAX_QUERY_LIMIT + 1)
                self.assertIsInstance(result, list)

    def test_default_limit_is_20(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(30):
                    store.add(self._make_event(i))
                result = store.list_recent()
                self.assertEqual(len(result), 20)

    def test_limit_exact_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(5):
                    store.add(self._make_event(i))
                result = store.list_recent(limit=5)
                self.assertEqual(len(result), 5)

    def test_limit_greater_than_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(3):
                    store.add(self._make_event(i))
                result = store.list_recent(limit=100)
                self.assertEqual(len(result), 3)


class TestAddAfterClose(unittest.TestCase):
    """Tests for add after close returns gracefully."""

    def test_add_after_close_does_not_crash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            event = ClipboardEvent(
                created_at=datetime.now(timezone.utc),
                image_hash="after_close",
                image_width=100,
                image_height=100,
                latex="x",
                source="test",
                status="ok",
                error=None,
            )
            store.add(event)

    def test_list_recent_after_close_returns_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            result = store.list_recent()
            self.assertEqual(result, [])

    def test_latest_after_close_returns_none(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            result = store.latest()
            self.assertIsNone(result)


class TestTruncateFieldAllTypes(unittest.TestCase):
    """Tests for _truncate_field for all field types."""

    def test_image_hash_truncation(self):
        val = "h" * 200
        result = _truncate_field(val, "image_hash")
        self.assertLessEqual(len(result), _MAX_FIELD_LENGTHS["image_hash"])
        self.assertTrue(result.endswith("..."))

    def test_latex_truncation(self):
        val = "x" * 70000
        result = _truncate_field(val, "latex")
        self.assertLessEqual(len(result), _MAX_FIELD_LENGTHS["latex"])
        self.assertTrue(result.endswith("..."))

    def test_source_truncation(self):
        val = "s" * 600
        result = _truncate_field(val, "source")
        self.assertLessEqual(len(result), _MAX_FIELD_LENGTHS["source"])
        self.assertTrue(result.endswith("..."))

    def test_status_truncation(self):
        val = "s" * 50
        result = _truncate_field(val, "status")
        self.assertLessEqual(len(result), _MAX_FIELD_LENGTHS["status"])
        self.assertTrue(result.endswith("..."))

    def test_error_truncation(self):
        val = "e" * 5000
        result = _truncate_field(val, "error")
        self.assertLessEqual(len(result), _MAX_FIELD_LENGTHS["error"])
        self.assertTrue(result.endswith("..."))

    def test_exact_max_length_not_truncated(self):
        for field_name, max_len in _MAX_FIELD_LENGTHS.items():
            with self.subTest(field=field_name):
                val = "x" * max_len
                result = _truncate_field(val, field_name)
                self.assertEqual(len(result), max_len)
                self.assertFalse(result.endswith("..."))

    def test_one_over_max_truncated(self):
        for field_name, max_len in _MAX_FIELD_LENGTHS.items():
            with self.subTest(field=field_name):
                val = "x" * (max_len + 1)
                result = _truncate_field(val, field_name)
                self.assertLessEqual(len(result), max_len)
                self.assertTrue(result.endswith("..."))

    def test_unknown_field_not_truncated(self):
        val = "x" * 100000
        result = _truncate_field(val, "unknown_field")
        self.assertEqual(result, val)

    def test_empty_string_unchanged(self):
        for field_name in _MAX_FIELD_LENGTHS:
            with self.subTest(field=field_name):
                self.assertEqual(_truncate_field("", field_name), "")

    def test_short_value_unchanged(self):
        for field_name in _MAX_FIELD_LENGTHS:
            with self.subTest(field=field_name):
                val = "short"
                self.assertEqual(_truncate_field(val, field_name), val)

    def test_truncation_preserves_prefix(self):
        val = "abcdefghij" * 20
        result = _truncate_field(val, "image_hash")
        max_len = _MAX_FIELD_LENGTHS["image_hash"]
        self.assertEqual(result[:max_len - 3], val[:max_len - 3])


class TestPathTraversal(unittest.TestCase):
    """Tests for path traversal rejection."""

    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            HistoryStore(Path("../../etc/history.sqlite3"))

    def test_path_traversal_with_mixed_segments(self):
        with self.assertRaises(ValueError):
            HistoryStore(Path("foo/../../etc/history.sqlite3"))

    def test_normal_path_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "history.sqlite3")
            store.close()

    def test_none_path_uses_default(self):
        store = HistoryStore(None)
        self.assertIsNotNone(store.db_path)
        store.close()

    def test_absolute_path_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir).resolve() / "history.sqlite3")
            self.assertIsNotNone(store.db_path)
            store.close()


class TestAutoVacuum(unittest.TestCase):
    """Tests for auto-vacuum behavior."""

    def _make_event(self, idx=0):
        return ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash=f"vacuum_{idx}",
            image_width=100,
            image_height=100,
            latex=f"x^{idx}",
            source="test",
            status="ok",
            error=None,
        )

    def test_auto_vacuum_under_limit_no_deletion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(10):
                    store.add(self._make_event(i))
                count = store._connection.execute(
                    "SELECT COUNT(*) FROM clipboard_history"
                ).fetchone()[0]
                self.assertEqual(count, 10)

    def test_auto_vacuum_triggers_when_over_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            import platex_client.history as history_mod
            original_max = history_mod._MAX_HISTORY_ROWS
            original_interval = history_mod._VACUUM_CHECK_INTERVAL
            try:
                history_mod._MAX_HISTORY_ROWS = 20
                history_mod._VACUUM_CHECK_INTERVAL = 5
                with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                    for i in range(30):
                        store.add(self._make_event(i))
                    count = store._connection.execute(
                        "SELECT COUNT(*) FROM clipboard_history"
                    ).fetchone()[0]
                    self.assertLessEqual(
                        count,
                        history_mod._MAX_HISTORY_ROWS + history_mod._VACUUM_CHECK_INTERVAL,
                    )
            finally:
                history_mod._MAX_HISTORY_ROWS = original_max
                history_mod._VACUUM_CHECK_INTERVAL = original_interval

    def test_vacuum_check_interval_constants(self):
        self.assertEqual(_VACUUM_CHECK_INTERVAL, 100)
        self.assertEqual(_MAX_HISTORY_ROWS, 50000)


class TestConcurrentWrites(unittest.TestCase):
    """Tests for concurrent write safety."""

    def _make_event(self, idx=0, thread_id=0):
        return ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash=f"concurrent_{thread_id}_{idx}",
            image_width=100,
            image_height=100,
            latex=f"x^{thread_id}_{idx}",
            source="concurrent_test",
            status="ok",
            error=None,
        )

    def test_concurrent_writes_no_errors(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            errors = []

            def writer(thread_id):
                try:
                    for i in range(10):
                        store.add(self._make_event(i, thread_id))
                except Exception as e:
                    errors.append(e)

            threads = [
                threading.Thread(target=writer, args=(i,)) for i in range(5)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
            self.assertEqual(len(errors), 0, f"Concurrent write errors: {errors}")
            store.close()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_concurrent_read_write(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            errors = []
            store.add(self._make_event(0, 0))

            def writer():
                try:
                    for i in range(20):
                        store.add(self._make_event(i, 1))
                except Exception as e:
                    errors.append(e)

            def reader():
                try:
                    for _ in range(20):
                        store.list_recent(limit=5)
                except Exception as e:
                    errors.append(e)

            threads = [
                threading.Thread(target=writer),
                threading.Thread(target=reader),
                threading.Thread(target=reader),
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=15)
            self.assertEqual(len(errors), 0, f"Concurrent read/write errors: {errors}")
            store.close()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestContextManager(unittest.TestCase):
    """Tests for context manager protocol."""

    def test_context_manager_closes_on_exit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(ClipboardEvent(
                    created_at=datetime.now(timezone.utc),
                    image_hash="ctx_test",
                    image_width=100,
                    image_height=100,
                    latex="ctx",
                    source="test",
                    status="ok",
                    error=None,
                ))
                self.assertFalse(store._closed)
            self.assertTrue(store._closed)

    def test_context_manager_returns_self(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            with store as ctx:
                self.assertIs(ctx, store)
            store.close()

    def test_exit_calls_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.__exit__(None, None, None)
            self.assertTrue(store._closed)
            # Double close should not raise
            store.__exit__(None, None, None)


class TestDoubleClose(unittest.TestCase):
    """Tests for double close safety."""

    def test_double_close_does_not_raise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            store.close()

    def test_triple_close_does_not_raise(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            store.close()
            store.close()


class TestLargeNumberOfRecords(unittest.TestCase):
    """Tests with large number of records."""

    def test_add_many_records(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(200):
                    store.add(ClipboardEvent(
                        created_at=datetime.now(timezone.utc),
                        image_hash=f"bulk_{i}",
                        image_width=100,
                        image_height=100,
                        latex=f"x^{i}",
                        source="bulk_test",
                        status="ok",
                        error=None,
                    ))
                result = store.list_recent(limit=50)
                self.assertEqual(len(result), 50)

    def test_list_recent_ordering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(10):
                    store.add(ClipboardEvent(
                        created_at=datetime(2024, 1, i + 1, 12, 0, 0, tzinfo=timezone.utc),
                        image_hash=f"order_{i}",
                        image_width=100,
                        image_height=100,
                        latex=f"x^{i}",
                        source="test",
                        status="ok",
                        error=None,
                    ))
                result = store.list_recent(limit=10)
                # Most recent first (by created_at DESC, then id DESC)
                self.assertEqual(len(result), 10)
                # The last event should have the latest created_at
                self.assertEqual(result[0].image_hash, "order_9")


class TestHistoryStoreConnectionRetry(unittest.TestCase):
    """Tests for connection retry logic."""

    def test_max_connect_retries_constant(self):
        self.assertEqual(HistoryStore._MAX_CONNECT_RETRIES, 3)

    def test_max_query_limit_constant(self):
        self.assertEqual(HistoryStore._MAX_QUERY_LIMIT, 10000)

    def test_reconnection_after_connection_loss(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            if store._connection is not None:
                try:
                    store._connection.close()
                except Exception:
                    pass
                store._connection = None
            event = ClipboardEvent(
                created_at=datetime.now(timezone.utc),
                image_hash="reconnect_test",
                image_width=100,
                image_height=100,
                latex="x^2",
                source="test",
                status="ok",
                error=None,
            )
            store.add(event)
            latest = store.latest()
            self.assertIsNotNone(latest)
            self.assertEqual(latest.image_hash, "reconnect_test")
            store.close()


class TestHistoryStoreRestrictPermissions(unittest.TestCase):
    """Tests for _restrict_db_file_permissions."""

    def test_restrict_permissions_does_not_crash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store._restrict_db_file_permissions()
            store.close()

    def test_restrict_permissions_nonexistent_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            # Should not crash even if file is gone
            store._restrict_db_file_permissions()


if __name__ == "__main__":
    unittest.main()
