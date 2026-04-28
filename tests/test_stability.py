from __future__ import annotations

import gc
import os
import queue
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
import weakref
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.app_state import AppState, StateMachine
from platex_client.config import AppConfig, ConfigStore, _parse_bool, load_config
from platex_client.events import (
    AppStateChangedEvent,
    EventBus,
    Event,
    OcrSuccessEvent,
    get_event_bus,
    reset_event_bus,
)
from platex_client.history import HistoryStore, _truncate_field, _MAX_HISTORY_ROWS
from platex_client.models import ClipboardEvent, OcrProcessor
from platex_client.popup_manager import PopupManager
from platex_client.script_context import SchedulerAPI
from platex_client.script_registry import ScriptRegistry
from platex_client.script_safety import (
    _check_dangerous_patterns,
    _load_script_module,
    scan_script_source,
    check_blocked_patterns,
    validate_script_path,
)
from platex_client.secrets import (
    clear_all,
    delete_secret,
    get_secret,
    has_secret,
    set_secret,
)
from platex_client.watcher import ClipboardWatcher


class TestHistoryStoreStability(unittest.TestCase):
    def test_double_close(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            store.close()
            store.close()

    def test_add_after_connection_loss(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
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

    def test_very_long_field_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with HistoryStore(db_path) as store:
                long_latex = "x" * 100000
                event = ClipboardEvent(
                    created_at=datetime.now(timezone.utc),
                    image_hash="h" * 200,
                    image_width=100,
                    image_height=100,
                    latex=long_latex,
                    source="s" * 600,
                    status="ok",
                    error=None,
                )
                store.add(event)
                latest = store.latest()
                self.assertIsNotNone(latest)
                self.assertLessEqual(len(latest.latex), 65536)
                self.assertLessEqual(len(latest.image_hash), 128)

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

    def test_concurrent_writes_stress(self):
        temp_dir = tempfile.mkdtemp()
        try:
            db_path = Path(temp_dir) / "test.sqlite3"
            store = HistoryStore(db_path)
            errors = []

            def writer(idx):
                try:
                    for i in range(10):
                        event = ClipboardEvent(
                            created_at=datetime.now(timezone.utc),
                            image_hash=f"stress_{idx}_{i}",
                            image_width=100,
                            image_height=100,
                            latex=f"x^{idx}_{i}",
                            source="stress_test",
                            status="ok",
                            error=None,
                        )
                        store.add(event)
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

    def test_list_recent_invalid_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with HistoryStore(db_path) as store:
                result = store.list_recent(limit=-1)
                self.assertIsInstance(result, list)
                result = store.list_recent(limit=0)
                self.assertIsInstance(result, list)
                result = store.list_recent(limit="invalid")
                self.assertIsInstance(result, list)

    def test_truncate_field(self):
        self.assertEqual(_truncate_field("short", "image_hash"), "short")
        long_val = "x" * 200
        truncated = _truncate_field(long_val, "image_hash")
        self.assertLessEqual(len(truncated), 128)
        self.assertTrue(truncated.endswith("..."))

    def test_auto_vacuum_under_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with HistoryStore(db_path) as store:
                for i in range(10):
                    event = ClipboardEvent(
                        created_at=datetime.now(timezone.utc),
                        image_hash=f"vacuum_{i}",
                        image_width=100,
                        image_height=100,
                        latex=f"x^{i}",
                        source="test",
                        status="ok",
                        error=None,
                    )
                    store.add(event)
                count = store._connection.execute("SELECT COUNT(*) FROM clipboard_history").fetchone()[0]
                self.assertLessEqual(count, _MAX_HISTORY_ROWS)

    def test_auto_vacuum_triggers_when_over_limit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with HistoryStore(db_path) as store:
                import platex_client.history as history_mod
                original_max = history_mod._MAX_HISTORY_ROWS
                original_interval = history_mod._VACUUM_CHECK_INTERVAL
                try:
                    history_mod._MAX_HISTORY_ROWS = 20
                    history_mod._VACUUM_CHECK_INTERVAL = 5
                    for i in range(30):
                        event = ClipboardEvent(
                            created_at=datetime.now(timezone.utc),
                            image_hash=f"vacuum_over_{i}",
                            image_width=100,
                            image_height=100,
                            latex=f"x^{i}",
                            source="test",
                            status="ok",
                            error=None,
                        )
                        store.add(event)
                    count = store._connection.execute("SELECT COUNT(*) FROM clipboard_history").fetchone()[0]
                    self.assertLessEqual(count, history_mod._MAX_HISTORY_ROWS + history_mod._VACUUM_CHECK_INTERVAL)
                finally:
                    history_mod._MAX_HISTORY_ROWS = original_max
                    history_mod._VACUUM_CHECK_INTERVAL = original_interval

    def test_context_manager_closes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with HistoryStore(db_path) as store:
                event = ClipboardEvent(
                    created_at=datetime.now(timezone.utc),
                    image_hash="ctx_test",
                    image_width=100,
                    image_height=100,
                    latex="ctx",
                    source="test",
                    status="ok",
                    error=None,
                )
                store.add(event)


class TestStateMachineStability(unittest.TestCase):
    def test_concurrent_transitions_no_deadlock(self):
        sm = StateMachine()
        errors = []

        def transition_loop():
            try:
                for _ in range(50):
                    sm.transition_to(AppState.STARTING)
                    sm.transition_to(AppState.RUNNING)
                    sm.transition_to(AppState.STOPPING)
                    sm.transition_to(AppState.STOPPED)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=transition_loop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"State machine concurrency errors: {errors}")

    def test_force_state_from_any_state(self):
        sm = StateMachine()
        sm.force_state(AppState.RUNNING)
        self.assertEqual(sm.state, AppState.RUNNING)
        sm.force_state(AppState.STOPPED)
        self.assertEqual(sm.state, AppState.STOPPED)

    def test_invalid_transition_returns_false(self):
        sm = StateMachine()
        result = sm.transition_to(AppState.STOPPING)
        self.assertFalse(result)
        self.assertEqual(sm.state, AppState.IDLE)

    def test_transition_callback_exception_does_not_break(self):
        sm = StateMachine()
        bad_called = threading.Event()
        good_called = threading.Event()

        def bad_cb(old, new):
            bad_called.set()
            raise RuntimeError("callback error")

        def good_cb(old, new):
            good_called.set()

        sm.on_transition(bad_cb)
        sm.on_transition(good_cb)
        result = sm.transition_to(AppState.STARTING)
        self.assertTrue(result)
        self.assertTrue(bad_called.wait(timeout=2))
        self.assertTrue(good_called.wait(timeout=2))

    def test_can_transition_to(self):
        sm = StateMachine()
        self.assertTrue(sm.can_transition_to(AppState.STARTING))
        self.assertFalse(sm.can_transition_to(AppState.RUNNING))

    def test_is_running_property(self):
        sm = StateMachine()
        self.assertFalse(sm.is_running)
        sm.force_state(AppState.RUNNING)
        self.assertTrue(sm.is_running)

    def test_is_stopped_property(self):
        sm = StateMachine()
        self.assertTrue(sm.is_stopped)
        sm.force_state(AppState.RUNNING)
        self.assertFalse(sm.is_stopped)
        sm.force_state(AppState.STOPPED)
        self.assertTrue(sm.is_stopped)


class TestEventBusStability(unittest.TestCase):
    def setUp(self):
        reset_event_bus()

    def tearDown(self):
        reset_event_bus()

    def test_emit_with_no_subscribers(self):
        bus = EventBus()
        bus.emit(OcrSuccessEvent(latex="test"))

    def test_subscriber_exception_does_not_break_others(self):
        bus = EventBus()
        bad_called = threading.Event()
        good_called = threading.Event()

        def bad_cb(event):
            bad_called.set()
            raise RuntimeError("subscriber error")

        def good_cb(event):
            good_called.set()

        bus.subscribe(OcrSuccessEvent, bad_cb)
        bus.subscribe(OcrSuccessEvent, good_cb)
        bus.emit(OcrSuccessEvent(latex="test"))

        self.assertTrue(bad_called.wait(timeout=2))
        self.assertTrue(good_called.wait(timeout=2))

    def test_unsubscribe_during_emit(self):
        bus = EventBus()
        called = threading.Event()

        def cb(event):
            called.set()
            bus.unsubscribe(OcrSuccessEvent, cb)

        bus.subscribe(OcrSuccessEvent, cb)
        bus.emit(OcrSuccessEvent(latex="test"))
        self.assertTrue(called.wait(timeout=2))

    def test_concurrent_subscribe_and_emit(self):
        bus = EventBus()
        errors = []

        def subscriber():
            try:
                for _ in range(50):
                    bus.subscribe(OcrSuccessEvent, lambda e: None)
            except Exception as e:
                errors.append(e)

        def emitter():
            try:
                for _ in range(50):
                    bus.emit(OcrSuccessEvent(latex="test"))
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=subscriber),
            threading.Thread(target=emitter),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"EventBus concurrency errors: {errors}")

    def test_weak_subscriber_gc_cleanup(self):
        bus = EventBus()
        received = []

        class Handler:
            def __call__(self, event):
                received.append(event)

        handler = Handler()
        bus.subscribe_weak(OcrSuccessEvent, handler)
        bus.emit(OcrSuccessEvent(latex="alive"))
        self.assertEqual(len(received), 1)

        ref = weakref.ref(handler)
        del handler
        gc.collect()

        bus.emit(OcrSuccessEvent(latex="after_gc"))
        self.assertIsNone(ref(), "Handler should be garbage collected")
        self.assertEqual(len(received), 1, "No more events should be received after GC")

    def test_unsubscribe_all(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.unsubscribe_all()
        self.assertEqual(len(bus._subscribers.get(OcrSuccessEvent, [])), 0)

    def test_unsubscribe_specific_event_type(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.subscribe(AppStateChangedEvent, lambda e: None)
        bus.unsubscribe_all(OcrSuccessEvent)
        self.assertIsNone(bus._subscribers.get(OcrSuccessEvent))
        self.assertIn(AppStateChangedEvent, bus._subscribers)

    def test_clear(self):
        bus = EventBus()
        bus.subscribe(OcrSuccessEvent, lambda e: None)
        bus.clear()
        bus.emit(OcrSuccessEvent())


class TestPopupManagerStability(unittest.TestCase):
    def test_show_popup_not_shutdown(self):
        pm = PopupManager()
        pm.show_popup("Title", "Latex content", 5000)
        self.assertFalse(pm.popup_queue.empty())

    def test_show_popup_when_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.show_popup("Title", "Latex content")
        self.assertTrue(pm.popup_queue.empty() or pm.popup_queue.get_nowait() is None)

    def test_open_panel_not_shutdown(self):
        pm = PopupManager()
        pm.open_panel()
        self.assertFalse(pm.panel_queue.empty())

    def test_open_panel_when_shutdown(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.open_panel()
        self.assertTrue(pm.panel_queue.empty() or pm.panel_queue.get_nowait() is None)

    def test_request_shutdown_idempotent(self):
        pm = PopupManager()
        pm.request_shutdown()
        pm.request_shutdown()
        self.assertTrue(pm.stop_event.is_set())

    def test_shutdown_confirm(self):
        pm = PopupManager()
        pm.request_shutdown()
        self.assertFalse(pm._shutdown_confirmed.is_set())
        pm.confirm_shutdown()
        self.assertTrue(pm._shutdown_confirmed.is_set())

    def test_wait_for_shutdown_timeout(self):
        pm = PopupManager()
        result = pm.wait_for_shutdown(timeout=0.1)
        self.assertFalse(result)

    def test_wait_for_shutdown_confirmed(self):
        pm = PopupManager()
        pm.confirm_shutdown()
        result = pm.wait_for_shutdown(timeout=1.0)
        self.assertTrue(result)

    def test_queue_overflow_drops_gracefully(self):
        pm = PopupManager()
        pm._popup_queue = queue.Queue(maxsize=3)
        for i in range(10):
            pm.show_popup("Title", f"Content {i}")
        count = 0
        while not pm.popup_queue.empty():
            try:
                pm.popup_queue.get_nowait()
                count += 1
            except queue.Empty:
                break
        self.assertLessEqual(count, 3)


class TestClipboardWatcherStability(unittest.TestCase):
    def _make_watcher(self, processor=None, history=None):
        if processor is None:
            class DummyProcessor(OcrProcessor):
                def process_image(self, image_bytes, context=None):
                    return "test"

            processor = DummyProcessor()

        if history is None:
            temp_dir = tempfile.mkdtemp()
            db_path = Path(temp_dir) / "test.sqlite3"
            history = HistoryStore(db_path)

        return ClipboardWatcher(
            processor=processor,
            history=history,
            source_name="test",
        )

    def test_poll_when_no_clipboard_image(self):
        watcher = self._make_watcher()
        with patch("platex_client.watcher.grab_image_clipboard", return_value=None):
            result = watcher.poll_once()
        self.assertIsNone(result)
        watcher.close()

    def test_poll_while_ocr_running(self):
        watcher = self._make_watcher()
        watcher._ocr_running.set()
        result = watcher.poll_once()
        self.assertIsNone(result)
        watcher._ocr_running.clear()
        watcher.close()

    def test_set_publishing_blocks_polling(self):
        watcher = self._make_watcher()
        watcher.set_publishing(True)
        self.assertTrue(watcher._paused.is_set())
        result = watcher.poll_once()
        self.assertIsNone(result)
        watcher.set_publishing(False)
        watcher.close()

    def test_close_waits_for_ocr(self):
        class SlowProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                time.sleep(0.3)
                return "slow"

        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=SlowProcessor(),
            history=history,
            source_name="test",
            ocr_timeout=5.0,
        )

        from platex_client.models import ClipboardImage
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            poll_thread = threading.Thread(target=watcher.poll_once)
            poll_thread.start()
            time.sleep(0.1)

        watcher.close()
        poll_thread.join(timeout=5)

    def test_ocr_timeout_handling(self):
        class HangingProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                time.sleep(10)
                return "never"

        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=HangingProcessor(),
            history=history,
            source_name="test",
            ocr_timeout=0.5,
        )

        from platex_client.models import ClipboardImage
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("timed out", result.error)
        watcher.close()

    def test_ocr_exception_handling(self):
        class FailingProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                raise RuntimeError("OCR engine failure")

        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")
        watcher = ClipboardWatcher(
            processor=FailingProcessor(),
            history=history,
            source_name="test",
        )

        from platex_client.models import ClipboardImage
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "error")
        self.assertIn("OCR engine failure", result.error)
        watcher.close()

    def test_history_write_failure_does_not_crash(self):
        class FailingHistory:
            def add(self, event):
                raise sqlite3.OperationalError("database is locked")

            def close(self):
                pass

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=FailingHistory(),
            source_name="test",
        )

        from platex_client.models import ClipboardImage
        fake_image = ClipboardImage(image_bytes=b"fake", width=10, height=10)

        with patch("platex_client.watcher.grab_image_clipboard", return_value=fake_image):
            result = watcher.poll_once()

        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ok")
        watcher.close()

    def test_close_safe_when_history_is_none(self):
        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )
        watcher.history = None
        watcher.close()
        history.close()

    def test_cleanup_orphan_threads(self):
        temp_dir = tempfile.mkdtemp()
        history = HistoryStore(Path(temp_dir) / "test.sqlite3")

        class DummyProcessor(OcrProcessor):
            def process_image(self, image_bytes, context=None):
                return "test"

        watcher = ClipboardWatcher(
            processor=DummyProcessor(),
            history=history,
            source_name="test",
        )
        dead_thread = threading.Thread(target=lambda: None)
        dead_thread.start()
        dead_thread.join()
        watcher._orphan_threads.append(dead_thread)
        watcher._cleanup_orphan_threads()
        self.assertEqual(len(watcher._orphan_threads), 0)
        watcher.close()


class TestSchedulerAPIStability(unittest.TestCase):
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

    def test_callback_exception_does_not_break_scheduler(self):
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

    def test_repeating_task_exception_continues(self):
        scheduler = SchedulerAPI()
        count = {"value": 0}

        def failing_cb():
            count["value"] += 1
            if count["value"] == 1:
                raise RuntimeError("first call fails")

        event = threading.Event()

        def stop_after():
            while count["value"] < 3:
                time.sleep(0.05)
            event.set()

        task = scheduler.schedule_repeating(0.1, failing_cb)
        stopper = threading.Thread(target=stop_after, daemon=True)
        stopper.start()
        self.assertTrue(event.wait(timeout=5.0))
        self.assertGreaterEqual(count["value"], 3)
        task.cancel()
        scheduler.cancel_all()

    def test_min_delay_clamped(self):
        scheduler = SchedulerAPI()
        fired = threading.Event()
        scheduler.schedule_once(0.001, fired.set)
        self.assertTrue(fired.wait(timeout=2.0))
        scheduler.cancel_all()


class TestSecretsStability(unittest.TestCase):
    def setUp(self):
        clear_all()

    def tearDown(self):
        clear_all()

    def test_concurrent_set_and_get(self):
        errors = []

        def writer():
            try:
                for i in range(100):
                    set_secret("KEY", f"value_{i}")
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(100):
                    result = get_secret("KEY")
                    self.assertIsInstance(result, str)
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
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Secrets concurrency errors: {errors}")

    def test_overwrite_secret_zeroes_old(self):
        set_secret("TEST", "old_value_12345")
        set_secret("TEST", "new_value")
        self.assertEqual(get_secret("TEST"), "new_value")

    def test_delete_nonexistent_key(self):
        delete_secret("NONEXISTENT")

    def test_clear_all_when_empty(self):
        clear_all()

    def test_unicode_secret_values(self):
        set_secret("UNICODE_KEY", "中文密钥 🔑")
        self.assertEqual(get_secret("UNICODE_KEY"), "中文密钥 🔑")

    def test_empty_value(self):
        set_secret("EMPTY_KEY", "")
        self.assertTrue(has_secret("EMPTY_KEY"))
        self.assertEqual(get_secret("EMPTY_KEY"), "")


class TestAppConfigApplyEnvironment(unittest.TestCase):
    def setUp(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_apply_with_none_values(self):
        cfg = AppConfig()
        cfg.apply_environment()
        self.assertFalse(has_secret("GLM_API_KEY"))
        self.assertFalse(has_secret("GLM_MODEL"))
        self.assertFalse(has_secret("GLM_BASE_URL"))

    def test_apply_does_not_overwrite_existing_secret(self):
        set_secret("GLM_API_KEY", "existing")
        cfg = AppConfig(glm_api_key="new")
        cfg.apply_environment()
        self.assertEqual(get_secret("GLM_API_KEY"), "existing")

    def test_apply_does_not_leak_to_environ(self):
        cfg = AppConfig(
            glm_api_key="secret1",
            glm_model="model1",
            glm_base_url="https://api.test.com",
        )
        cfg.apply_environment()
        self.assertIsNone(os.environ.get("GLM_API_KEY"))
        self.assertIsNone(os.environ.get("GLM_MODEL"))
        self.assertIsNone(os.environ.get("GLM_BASE_URL"))


class TestConfigEdgeCases(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_malformed_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(":\n  :\n    - invalid: [yaml: content", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_config_with_non_dict_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_config(config_path)

    def test_config_with_null_payload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("---\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.8)

    def test_json_config_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.json"
            config_path.write_text('{"interval": 2.0, "isolate_mode": true}', encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 2.0)
            self.assertTrue(cfg.isolate_mode)

    def test_interval_boundary_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("interval: 0.1\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 0.1)

            config_path.write_text("interval: 60.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

            config_path.write_text("interval: 100.0\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.interval, 60.0)

    def test_invalid_language_code(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text("ui_language: xx-yy\n", encoding="utf-8")
            cfg = load_config(config_path)
            self.assertEqual(cfg.ui_language, "en")

    def test_config_store_save_and_reload(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir, config_file_path
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()

            store = ConfigStore.instance()
            store.request_update_and_save({"interval": 3.0, "auto_start": True})

            saved_path = config_file_path()
            self.assertTrue(saved_path.exists())

            reloaded = load_config(saved_path)
            self.assertEqual(reloaded.interval, 3.0)
            self.assertTrue(reloaded.auto_start)

    def test_config_store_concurrent_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()

            store = ConfigStore.instance()
            errors = []

            def updater(idx):
                try:
                    store.request_update_and_save({"interval": float(idx)})
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=updater, args=(i,)) for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            self.assertEqual(len(errors), 0, f"Concurrent config update errors: {errors}")

    def test_config_store_update_invalid_interval_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.config_manager import set_config_dir
            set_config_dir(Path(temp_dir))
            ConfigStore.reset()
            store = ConfigStore.instance()
            original = store.config.interval
            store.request_update_and_save({"interval": "not_a_number"})
            self.assertEqual(store.config.interval, original)

    def test_parse_bool_edge_cases(self):
        self.assertTrue(_parse_bool("ON"))
        self.assertTrue(_parse_bool("Yes"))
        self.assertTrue(_parse_bool("1"))
        self.assertFalse(_parse_bool("FALSE"))
        self.assertFalse(_parse_bool("0"))
        self.assertFalse(_parse_bool("No"))
        self.assertFalse(_parse_bool("OFF"))
        self.assertFalse(_parse_bool(""))
        self.assertFalse(_parse_bool(None))


class TestConfigManagerStability(unittest.TestCase):
    def test_import_nonexistent_file(self):
        from platex_client.config_manager import ConfigManager
        cm = ConfigManager()
        with self.assertRaises(FileNotFoundError):
            cm.import_all(Path("/nonexistent/config.yaml"))

    def test_import_oversized_file(self):
        from platex_client.config_manager import ConfigManager
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            big_file = Path(temp_dir) / "big.yaml"
            big_file.write_bytes(b"x: " + b"a" * (2 * 1024 * 1024))
            with self.assertRaises(ValueError):
                cm.import_all(big_file)

    def test_import_non_dict_yaml(self):
        from platex_client.config_manager import ConfigManager
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "list.yaml"
            yaml_file.write_text("- item1\n- item2\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                cm.import_all(yaml_file)

    def test_import_empty_yaml(self):
        from platex_client.config_manager import ConfigManager
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "empty.yaml"
            yaml_file.write_text("---\n", encoding="utf-8")
            result = cm.import_all(yaml_file)
            self.assertEqual(result, {})

    def test_import_script_nonexistent_file(self):
        from platex_client.config_manager import ConfigManager
        cm = ConfigManager()
        with self.assertRaises(FileNotFoundError):
            cm.import_script(Path("/nonexistent/script.yaml"))

    def test_export_script_no_registry(self):
        from platex_client.config_manager import ConfigManager
        cm = ConfigManager()
        with self.assertRaises(RuntimeError):
            cm.export_script("test", Path("/tmp/test.yaml"))

    def test_export_script_not_found(self):
        from platex_client.config_manager import ConfigManager
        registry = MagicMock()
        registry.get.return_value = None
        cm = ConfigManager(registry)
        with self.assertRaises(ValueError):
            cm.export_script("nonexistent", Path("/tmp/test.yaml"))

    def test_import_filters_unknown_keys(self):
        from platex_client.config_manager import ConfigManager
        cm = ConfigManager()
        with tempfile.TemporaryDirectory() as temp_dir:
            yaml_file = Path(temp_dir) / "extra.yaml"
            yaml_file.write_text(
                "general:\n  interval: 1.5\n  dangerous_key: hack\n",
                encoding="utf-8",
            )
            result = cm.import_all(yaml_file)
            self.assertIn("general", result)
            self.assertNotIn("dangerous_key", result["general"])

    def test_deep_merge(self):
        from platex_client.config_manager import deep_merge
        base = {"a": 1, "b": {"c": 2, "d": 3}}
        override = {"b": {"c": 99}, "e": 5}
        result = deep_merge(base, override)
        self.assertEqual(result["a"], 1)
        self.assertEqual(result["b"]["c"], 99)
        self.assertEqual(result["b"]["d"], 3)
        self.assertEqual(result["e"], 5)

    def test_deep_merge_does_not_modify_original(self):
        from platex_client.config_manager import deep_merge
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        result = deep_merge(base, override)
        self.assertNotIn("y", base["a"])


class TestScriptSafetyStability(unittest.TestCase):
    def test_empty_script_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "empty.py"
            script_path.write_text("", encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(script_path)

    def test_oversized_script_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "big.py"
            script_path.write_text("x = 1\n" * 200000, encoding="utf-8")
            with self.assertRaises(ValueError):
                validate_script_path(script_path)

    def test_nonexistent_script_file(self):
        with self.assertRaises(FileNotFoundError):
            validate_script_path(Path("/nonexistent/script.py"))

    def test_script_with_syntax_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "bad_syntax.py"
            script_path.write_text("def broken(\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                _load_script_module(script_path)

    def test_script_with_runtime_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "runtime_error.py"
            script_path.write_text(
                "raise RuntimeError('script init error')\n"
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            with self.assertRaises(RuntimeError):
                _load_script_module(script_path)

    def test_check_dangerous_patterns_blocked(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dangerous.py"
            script_path.write_text(
                "import os\nos.system('echo pwned')\n"
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                _check_dangerous_patterns(script_path)

    def test_safe_script_passes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "safe.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'safe result'\n",
                encoding="utf-8",
            )
            _check_dangerous_patterns(script_path)

    def test_blocked_patterns_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "evil.py"
            script_path.write_text(
                "import os\nos.system('rm -rf /')\n"
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            warnings, blocked = scan_script_source(script_path)
            self.assertTrue(len(blocked) > 0, "os.system should be blocked")

    def test_check_blocked_patterns(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "evil.py"
            script_path.write_text(
                "exec('print(1)')\n"
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            blocked = check_blocked_patterns(script_path)
            self.assertIn("exec()", blocked)


class TestScriptRegistryStability(unittest.TestCase):
    def test_load_nonexistent_script(self):
        registry = ScriptRegistry()
        result = registry.load_script_file(Path("/nonexistent/script.py"))
        self.assertIsNone(result)

    def test_discover_from_nonexistent_dir(self):
        registry = ScriptRegistry()
        registry.discover_scripts(Path("/nonexistent/scripts"))

    def test_load_script_with_unsupported_interface(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "no_interface.py"
            script_path.write_text("x = 42\n", encoding="utf-8")
            registry = ScriptRegistry()
            result = registry._load_script_file(script_path)
            self.assertIsNone(result)

    def test_load_configs_with_invalid_config(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            registry.load_configs({"test": "not_a_dict"})

    def test_get_ocr_scripts(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "ocr_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            ocr_scripts = registry.get_ocr_scripts()
            self.assertGreaterEqual(len(ocr_scripts), 1)

    def test_get_hotkey_scripts_empty(self):
        registry = ScriptRegistry()
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "no_hotkey.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            registry._load_script_file(script_path)
            hotkey_scripts = registry.get_hotkey_scripts()
            self.assertEqual(len(hotkey_scripts), 0)


class TestLoaderStability(unittest.TestCase):
    def test_load_script_returning_dict(self):
        from platex_client.loader import load_script_processor
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "dict_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n"
                "    return {'latex': r'x^2 + y^2'}\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            result = processor.process_image(b"test", {})
            self.assertEqual(result, "x^2 + y^2")

    def test_load_script_returning_unsupported_type(self):
        from platex_client.loader import load_script_processor
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "bad_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n"
                "    return 42\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError):
                processor.process_image(b"test", {})

    def test_load_script_returning_empty_string(self):
        from platex_client.loader import load_script_processor
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "empty_return.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n"
                "    return '  '\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            with self.assertRaises(RuntimeError):
                processor.process_image(b"test", {})

    def test_load_script_with_process_image(self):
        from platex_client.loader import load_script_processor
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "legacy.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return r'\\alpha'\n",
                encoding="utf-8",
            )
            processor = load_script_processor(script_path)
            result = processor.process_image(b"test", {})
            self.assertEqual(result, r"\alpha")

    def test_load_script_no_entry_point(self):
        from platex_client.loader import load_script_processor
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "noop.py"
            script_path.write_text("x = 42\n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                load_script_processor(script_path)


class TestI18nStability(unittest.TestCase):
    def test_initialize_with_invalid_language(self):
        from platex_client.i18n import initialize, get_current_language
        initialize("nonexistent")
        self.assertEqual(get_current_language(), "en")

    def test_t_returns_key_for_missing_translation(self):
        from platex_client.i18n import initialize, t
        initialize("en")
        result = t("nonexistent.key.12345")
        self.assertEqual(result, "nonexistent.key.12345")

    def test_available_languages(self):
        from platex_client.i18n import available_languages
        langs = available_languages()
        self.assertIsInstance(langs, list)
        for code, name in langs:
            self.assertIsInstance(code, str)
            self.assertIsInstance(name, str)


if __name__ == "__main__":
    unittest.main()
