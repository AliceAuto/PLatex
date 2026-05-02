from __future__ import annotations

import gc
import shutil
import tempfile
import threading
import time
import unittest
import weakref
from datetime import datetime, timezone
from pathlib import Path

from platex_client.history import (
    HistoryStore,
    _MAX_FIELD_LENGTHS,
    _MAX_HISTORY_ROWS,
    _VACUUM_CHECK_INTERVAL,
    _truncate_field,
)
from platex_client.models import ClipboardEvent


class TestTruncateField(unittest.TestCase):
    def test_short_value_unchanged(self):
        self.assertEqual(_truncate_field("short", "image_hash"), "short")

    def test_exact_max_length_unchanged(self):
        val = "x" * 128
        self.assertEqual(_truncate_field(val, "image_hash"), val)

    def test_over_max_truncated(self):
        val = "x" * 200
        result = _truncate_field(val, "image_hash")
        self.assertLessEqual(len(result), 128)
        self.assertTrue(result.endswith("..."))

    def test_latex_truncation(self):
        val = "x" * 70000
        result = _truncate_field(val, "latex")
        self.assertLessEqual(len(result), 65536)
        self.assertTrue(result.endswith("..."))

    def test_source_truncation(self):
        val = "s" * 600
        result = _truncate_field(val, "source")
        self.assertLessEqual(len(result), 512)
        self.assertTrue(result.endswith("..."))

    def test_error_truncation(self):
        val = "e" * 5000
        result = _truncate_field(val, "error")
        self.assertLessEqual(len(result), 4096)
        self.assertTrue(result.endswith("..."))

    def test_status_truncation(self):
        val = "s" * 50
        result = _truncate_field(val, "status")
        self.assertLessEqual(len(result), 32)
        self.assertTrue(result.endswith("..."))

    def test_unknown_field_not_truncated(self):
        val = "x" * 10000
        result = _truncate_field(val, "unknown_field")
        self.assertEqual(result, val)

    def test_empty_string_unchanged(self):
        self.assertEqual(_truncate_field("", "image_hash"), "")

    def test_one_over_max(self):
        val = "x" * 129
        result = _truncate_field(val, "image_hash")
        self.assertLessEqual(len(result), 128)
        self.assertTrue(result.endswith("..."))


class TestHistoryStoreBasic(unittest.TestCase):
    def _make_event(self, **kwargs):
        defaults = dict(
            created_at=datetime.now(timezone.utc),
            image_hash="abc123",
            image_width=120,
            image_height=80,
            latex=r"x^2+y^2=z^2",
            source="test",
            status="ok",
            error=None,
        )
        defaults.update(kwargs)
        return ClipboardEvent(**defaults)

    def test_add_and_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                latest = store.latest()
                self.assertIsNotNone(latest)
                self.assertEqual(latest.image_hash, "abc123")

    def test_latest_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                self.assertIsNone(store.latest())

    def test_add_multiple_and_list_recent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(10):
                    store.add(self._make_event(image_hash=f"hash_{i}", latex=f"x^{i}"))
                recent = store.list_recent(limit=5)
                self.assertEqual(len(recent), 5)
                self.assertEqual(recent[0].image_hash, "hash_9")

    def test_list_recent_default_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(25):
                    store.add(self._make_event(image_hash=f"hash_{i}"))
                recent = store.list_recent()
                self.assertEqual(len(recent), 20)

    def test_list_recent_invalid_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                result = store.list_recent(limit=-1)
                self.assertIsInstance(result, list)
                result = store.list_recent(limit=0)
                self.assertIsInstance(result, list)
                result = store.list_recent(limit="invalid")
                self.assertIsInstance(result, list)

    def test_list_recent_large_limit_clamped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event())
                result = store.list_recent(limit=20000)
                self.assertIsInstance(result, list)

    def test_error_event(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event(status="error", error="Something went wrong", latex=""))
                latest = store.latest()
                self.assertIsNotNone(latest)
                self.assertEqual(latest.status, "error")
                self.assertEqual(latest.error, "Something went wrong")

    def test_event_with_none_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event(error=None))
                latest = store.latest()
                self.assertIsNone(latest.error)

    def test_event_with_empty_latex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event(latex=""))
                latest = store.latest()
                self.assertEqual(latest.latex, "")

    def test_unicode_latex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                store.add(self._make_event(latex="α + β = γ"))
                latest = store.latest()
                self.assertEqual(latest.latex, "α + β = γ")


class TestHistoryStorePathTraversal(unittest.TestCase):
    def test_path_traversal_rejected(self):
        with self.assertRaises(ValueError):
            HistoryStore(Path("../../etc/history.sqlite3"))

    def test_normal_path_accepted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "history.sqlite3")
            store.close()

    def test_none_path_uses_default(self):
        store = HistoryStore(None)
        self.assertIsNotNone(store.db_path)
        store.close()


class TestHistoryStoreConnection(unittest.TestCase):
    def test_double_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            store.close()

    def test_add_after_connection_loss(self):
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

    def test_add_after_close_does_not_crash(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            event = ClipboardEvent(
                created_at=datetime.now(timezone.utc),
                image_hash="after_close",
                image_width=100,
                image_height=100,
                latex="x^2",
                source="test",
                status="ok",
                error=None,
            )
            store.add(event)

    def test_list_recent_after_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = HistoryStore(Path(temp_dir) / "test.sqlite3")
            store.close()
            result = store.list_recent()
            self.assertEqual(result, [])

    def test_context_manager(self):
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
            self.assertTrue(store._closed)


class TestHistoryStoreLongFields(unittest.TestCase):
    def test_very_long_latex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                long_latex = "x" * 100000
                store.add(ClipboardEvent(
                    created_at=datetime.now(timezone.utc),
                    image_hash="h" * 200,
                    image_width=100,
                    image_height=100,
                    latex=long_latex,
                    source="s" * 600,
                    status="ok",
                    error=None,
                ))
                latest = store.latest()
                self.assertIsNotNone(latest)
                self.assertLessEqual(len(latest.latex), 65536)
                self.assertLessEqual(len(latest.image_hash), 128)
                self.assertLessEqual(len(latest.source), 512)

    def test_very_long_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                long_error = "e" * 10000
                store.add(ClipboardEvent(
                    created_at=datetime.now(timezone.utc),
                    image_hash="err_hash",
                    image_width=100,
                    image_height=100,
                    latex="",
                    source="test",
                    status="error",
                    error=long_error,
                ))
                latest = store.latest()
                self.assertLessEqual(len(latest.error), 4096)


class TestHistoryStoreConcurrency(unittest.TestCase):
    def test_concurrent_writes(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            errors = []

            def writer(idx):
                try:
                    for i in range(10):
                        store.add(ClipboardEvent(
                            created_at=datetime.now(timezone.utc),
                            image_hash=f"stress_{idx}_{i}",
                            image_width=100,
                            image_height=100,
                            latex=f"x^{idx}_{i}",
                            source="stress_test",
                            status="ok",
                            error=None,
                        ))
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
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
            store.add(ClipboardEvent(
                created_at=datetime.now(timezone.utc),
                image_hash="initial",
                image_width=100,
                image_height=100,
                latex="x",
                source="test",
                status="ok",
                error=None,
            ))

            def writer():
                try:
                    for i in range(20):
                        store.add(ClipboardEvent(
                            created_at=datetime.now(timezone.utc),
                            image_hash=f"rw_{i}",
                            image_width=100,
                            image_height=100,
                            latex=f"x^{i}",
                            source="test",
                            status="ok",
                            error=None,
                        ))
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


class TestHistoryStoreAutoVacuum(unittest.TestCase):
    def test_auto_vacuum_under_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                for i in range(10):
                    store.add(ClipboardEvent(
                        created_at=datetime.now(timezone.utc),
                        image_hash=f"vacuum_{i}",
                        image_width=100,
                        image_height=100,
                        latex=f"x^{i}",
                        source="test",
                        status="ok",
                        error=None,
                    ))
                count = store._connection.execute("SELECT COUNT(*) FROM clipboard_history").fetchone()[0]
                self.assertLessEqual(count, _MAX_HISTORY_ROWS)

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
                        store.add(ClipboardEvent(
                            created_at=datetime.now(timezone.utc),
                            image_hash=f"vacuum_over_{i}",
                            image_width=100,
                            image_height=100,
                            latex=f"x^{i}",
                            source="test",
                            status="ok",
                            error=None,
                        ))
                    count = store._connection.execute("SELECT COUNT(*) FROM clipboard_history").fetchone()[0]
                    self.assertLessEqual(count, history_mod._MAX_HISTORY_ROWS + history_mod._VACUUM_CHECK_INTERVAL)
            finally:
                history_mod._MAX_HISTORY_ROWS = original_max
                history_mod._VACUUM_CHECK_INTERVAL = original_interval


class TestHistoryStoreCorruptedDb(unittest.TestCase):
    def test_corrupted_database_recovery(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test.sqlite3"
            db_path.write_bytes(b"not a valid sqlite database content")
            try:
                store = HistoryStore(db_path)
                store.close()
            except Exception:
                pass
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestHistoryStoreEnsureUtc(unittest.TestCase):
    def test_naive_datetime_gets_utc(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                naive_dt = datetime(2024, 1, 1, 12, 0, 0)
                store.add(ClipboardEvent(
                    created_at=naive_dt,
                    image_hash="naive_dt",
                    image_width=100,
                    image_height=100,
                    latex="x",
                    source="test",
                    status="ok",
                    error=None,
                ))
                latest = store.latest()
                self.assertIsNotNone(latest)
                self.assertIsNotNone(latest.created_at.tzinfo)

    def test_aware_datetime_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with HistoryStore(Path(temp_dir) / "test.sqlite3") as store:
                aware_dt = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
                store.add(ClipboardEvent(
                    created_at=aware_dt,
                    image_hash="aware_dt",
                    image_width=100,
                    image_height=100,
                    latex="x",
                    source="test",
                    status="ok",
                    error=None,
                ))
                latest = store.latest()
                self.assertIsNotNone(latest)


if __name__ == "__main__":
    unittest.main()
