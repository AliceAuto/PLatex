from __future__ import annotations

import logging
import threading
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, call

from platex_client.models import ClipboardEvent, ClipboardImage
from platex_client.script_context import (
    ClipboardAPI,
    ConfigAPI,
    HistoryAPI,
    HotkeyAPI,
    LoggerAPI,
    MouseAPI,
    NotificationAPI,
    SchedulerAPI,
    ScriptContext,
    WindowAPI,
    _ScheduledTask,
)


# ---------------------------------------------------------------------------
# ClipboardAPI
# ---------------------------------------------------------------------------

class TestClipboardAPI(unittest.TestCase):

    # -- helpers --

    def _make_api(self, *, read_text_return=None, read_image_return=None):
        return ClipboardAPI(
            read_text_fn=MagicMock(return_value=read_text_return),
            write_text_fn=MagicMock(),
            read_image_fn=MagicMock(return_value=read_image_return),
        )

    # -- read_text --

    def test_read_text_returns_string(self):
        api = self._make_api(read_text_return="hello world")
        self.assertEqual(api.read_text(), "hello world")

    def test_read_text_returns_none(self):
        api = self._make_api(read_text_return=None)
        self.assertIsNone(api.read_text())

    def test_read_text_delegates_to_fn(self):
        fn = MagicMock(return_value="abc")
        api = ClipboardAPI(read_text_fn=fn, write_text_fn=MagicMock(), read_image_fn=MagicMock(return_value=None))
        api.read_text()
        fn.assert_called_once_with()

    def test_read_text_propagates_exception(self):
        api = ClipboardAPI(
            read_text_fn=MagicMock(side_effect=RuntimeError("clipboard busy")),
            write_text_fn=MagicMock(),
            read_image_fn=MagicMock(return_value=None),
        )
        with self.assertRaises(RuntimeError):
            api.read_text()

    def test_read_text_empty_string(self):
        api = self._make_api(read_text_return="")
        self.assertEqual(api.read_text(), "")

    # -- write_text --

    def test_write_text_delegates(self):
        api = self._make_api()
        api.write_text("world")
        api._write_text.assert_called_once_with("world")

    def test_write_text_empty_string(self):
        api = self._make_api()
        api.write_text("")
        api._write_text.assert_called_once_with("")

    def test_write_text_unicode(self):
        api = self._make_api()
        api.write_text("\u4f60\u597d\u4e16\u754c \U0001f30d")
        api._write_text.assert_called_once_with("\u4f60\u597d\u4e16\u754c \U0001f30d")

    def test_write_text_long_string(self):
        api = self._make_api()
        long_text = "x" * 100_000
        api.write_text(long_text)
        api._write_text.assert_called_once_with(long_text)

    def test_write_text_propagates_exception(self):
        api = ClipboardAPI(
            read_text_fn=MagicMock(return_value=None),
            write_text_fn=MagicMock(side_effect=OSError("write failed")),
            read_image_fn=MagicMock(return_value=None),
        )
        with self.assertRaises(OSError):
            api.write_text("fail")

    # -- read_image --

    def test_read_image_none(self):
        api = self._make_api(read_image_return=None)
        self.assertIsNone(api.read_image())

    def test_read_image_with_data(self):
        img = ClipboardImage(image_bytes=b"\x89PNG", width=100, height=200)
        api = self._make_api(read_image_return=img)
        result = api.read_image()
        self.assertIsNotNone(result)
        self.assertEqual(result.width, 100)
        self.assertEqual(result.height, 200)
        self.assertEqual(result.image_bytes, b"\x89PNG")

    def test_read_image_delegates_to_fn(self):
        fn = MagicMock(return_value=None)
        api = ClipboardAPI(read_text_fn=MagicMock(return_value=None), write_text_fn=MagicMock(), read_image_fn=fn)
        api.read_image()
        fn.assert_called_once_with()

    def test_read_image_propagates_exception(self):
        api = ClipboardAPI(
            read_text_fn=MagicMock(return_value=None),
            write_text_fn=MagicMock(),
            read_image_fn=MagicMock(side_effect=RuntimeError("image read error")),
        )
        with self.assertRaises(RuntimeError):
            api.read_image()

    # -- constructor keyword-only --

    def test_constructor_requires_keyword_args(self):
        with self.assertRaises(TypeError):
            ClipboardAPI(MagicMock(), MagicMock(), MagicMock())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HotkeyAPI
# ---------------------------------------------------------------------------

class TestHotkeyAPI(unittest.TestCase):

    def _make_api(self, *, register_return=True):
        return HotkeyAPI(
            register_fn=MagicMock(return_value=register_return),
            unregister_fn=MagicMock(),
        )

    # -- register --

    def test_register_success_returns_true(self):
        api = self._make_api(register_return=True)
        cb = lambda: None
        result = api.register("Ctrl+Alt+K", cb)
        self.assertTrue(result)

    def test_register_failure_returns_false(self):
        api = self._make_api(register_return=False)
        result = api.register("Ctrl+A", lambda: None)
        self.assertFalse(result)

    def test_register_delegates_with_hotkey_and_callback(self):
        register_fn = MagicMock(return_value=True)
        api = HotkeyAPI(register_fn=register_fn, unregister_fn=MagicMock())
        cb = lambda: None
        api.register("Ctrl+Shift+F5", cb)
        register_fn.assert_called_once_with("Ctrl+Shift+F5", cb)

    def test_register_multiple_hotkeys(self):
        register_fn = MagicMock(return_value=True)
        api = HotkeyAPI(register_fn=register_fn, unregister_fn=MagicMock())
        api.register("Ctrl+1", lambda: None)
        api.register("Ctrl+2", lambda: None)
        self.assertEqual(register_fn.call_count, 2)

    def test_register_propagates_exception(self):
        api = HotkeyAPI(
            register_fn=MagicMock(side_effect=ValueError("invalid hotkey")),
            unregister_fn=MagicMock(),
        )
        with self.assertRaises(ValueError):
            api.register("!!!", lambda: None)

    # -- unregister --

    def test_unregister_delegates(self):
        unregister_fn = MagicMock()
        api = HotkeyAPI(register_fn=MagicMock(return_value=True), unregister_fn=unregister_fn)
        api.unregister("Ctrl+Alt+K")
        unregister_fn.assert_called_once_with("Ctrl+Alt+K")

    def test_unregister_propagates_exception(self):
        api = HotkeyAPI(
            register_fn=MagicMock(return_value=True),
            unregister_fn=MagicMock(side_effect=KeyError("not registered")),
        )
        with self.assertRaises(KeyError):
            api.unregister("Ctrl+X")

    # -- constructor keyword-only --

    def test_constructor_requires_keyword_args(self):
        with self.assertRaises(TypeError):
            HotkeyAPI(MagicMock(), MagicMock())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# NotificationAPI
# ---------------------------------------------------------------------------

class TestNotificationAPI(unittest.TestCase):

    def _make_api(self):
        return NotificationAPI(
            show_fn=MagicMock(),
            show_ocr_fn=MagicMock(),
        )

    # -- show --

    def test_show_default_timeout(self):
        api = self._make_api()
        api.show("Title", "Message")
        api._show.assert_called_once_with("Title", "Message", 5000)

    def test_show_custom_timeout(self):
        api = self._make_api()
        api.show("Title", "Message", timeout_ms=10000)
        api._show.assert_called_once_with("Title", "Message", 10000)

    def test_show_zero_timeout(self):
        api = self._make_api()
        api.show("Title", "Message", timeout_ms=0)
        api._show.assert_called_once_with("Title", "Message", 0)

    def test_show_empty_strings(self):
        api = self._make_api()
        api.show("", "")
        api._show.assert_called_once_with("", "", 5000)

    def test_show_unicode(self):
        api = self._make_api()
        api.show("\u6807\u9898", "\u6d88\u606f")
        api._show.assert_called_once_with("\u6807\u9898", "\u6d88\u606f", 5000)

    def test_show_propagates_exception(self):
        api = NotificationAPI(
            show_fn=MagicMock(side_effect=RuntimeError("show failed")),
            show_ocr_fn=MagicMock(),
        )
        with self.assertRaises(RuntimeError):
            api.show("T", "M")

    # -- show_ocr_result --

    def test_show_ocr_result_default_timeout(self):
        api = self._make_api()
        api.show_ocr_result("x^2 + y^2 = z^2")
        api._show_ocr.assert_called_once_with("x^2 + y^2 = z^2", 12000)

    def test_show_ocr_result_custom_timeout(self):
        api = self._make_api()
        api.show_ocr_result("E=mc^2", timeout_ms=5000)
        api._show_ocr.assert_called_once_with("E=mc^2", 5000)

    def test_show_ocr_result_empty_latex(self):
        api = self._make_api()
        api.show_ocr_result("")
        api._show_ocr.assert_called_once_with("", 12000)

    def test_show_ocr_result_unicode(self):
        api = self._make_api()
        api.show_ocr_result("\\alpha + \\beta")
        api._show_ocr.assert_called_once_with("\\alpha + \\beta", 12000)

    def test_show_ocr_result_propagates_exception(self):
        api = NotificationAPI(
            show_fn=MagicMock(),
            show_ocr_fn=MagicMock(side_effect=RuntimeError("ocr show failed")),
        )
        with self.assertRaises(RuntimeError):
            api.show_ocr_result("x")

    # -- constructor keyword-only --

    def test_constructor_requires_keyword_args(self):
        with self.assertRaises(TypeError):
            NotificationAPI(MagicMock(), MagicMock())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# WindowAPI
# ---------------------------------------------------------------------------

class TestWindowAPI(unittest.TestCase):

    def _make_api(self, *, title="Test Window"):
        return WindowAPI(get_foreground_title_fn=MagicMock(return_value=title))

    def test_get_foreground_title(self):
        api = self._make_api(title="VS Code")
        self.assertEqual(api.get_foreground_title(), "VS Code")

    def test_get_foreground_title_empty(self):
        api = self._make_api(title="")
        self.assertEqual(api.get_foreground_title(), "")

    def test_get_foreground_title_unicode(self):
        api = self._make_api(title="\u7a97\u53e3\u6807\u9898")
        self.assertEqual(api.get_foreground_title(), "\u7a97\u53e3\u6807\u9898")

    def test_get_foreground_title_delegates(self):
        fn = MagicMock(return_value="Title")
        api = WindowAPI(get_foreground_title_fn=fn)
        api.get_foreground_title()
        fn.assert_called_once_with()

    def test_get_foreground_title_propagates_exception(self):
        api = WindowAPI(get_foreground_title_fn=MagicMock(side_effect=OSError("no window")))
        with self.assertRaises(OSError):
            api.get_foreground_title()

    def test_constructor_requires_keyword_args(self):
        with self.assertRaises(TypeError):
            WindowAPI(MagicMock())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# MouseAPI
# ---------------------------------------------------------------------------

class TestMouseAPI(unittest.TestCase):

    def _make_api(self):
        return MouseAPI(click_fn=MagicMock())

    def test_click_default_button(self):
        api = self._make_api()
        api.click(100, 200)
        api._click.assert_called_once_with(100, 200, "left")

    def test_click_right_button(self):
        api = self._make_api()
        api.click(300, 400, button="right")
        api._click.assert_called_once_with(300, 400, "right")

    def test_click_zero_coords(self):
        api = self._make_api()
        api.click(0, 0)
        api._click.assert_called_once_with(0, 0, "left")

    def test_click_negative_coords(self):
        api = self._make_api()
        api.click(-1, -1, button="right")
        api._click.assert_called_once_with(-1, -1, "right")

    def test_click_large_coords(self):
        api = self._make_api()
        api.click(3840, 2160)
        api._click.assert_called_once_with(3840, 2160, "left")

    def test_click_propagates_exception(self):
        api = MouseAPI(click_fn=MagicMock(side_effect=RuntimeError("click failed")))
        with self.assertRaises(RuntimeError):
            api.click(0, 0)

    def test_constructor_requires_keyword_args(self):
        with self.assertRaises(TypeError):
            MouseAPI(MagicMock())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SchedulerAPI (basic; detailed tests in test_stability.py)
# ---------------------------------------------------------------------------

class TestSchedulerAPI(unittest.TestCase):

    def test_schedule_once_fires(self):
        scheduler = SchedulerAPI()
        called = threading.Event()
        scheduler.schedule_once(0.05, called.set)
        self.assertTrue(called.wait(timeout=2))

    def test_schedule_once_cancel_prevents_fire(self):
        scheduler = SchedulerAPI()
        called = threading.Event()
        task = scheduler.schedule_once(0.5, called.set)
        task.cancel()
        self.assertFalse(called.wait(timeout=1))

    def test_schedule_repeating_fires_multiple(self):
        scheduler = SchedulerAPI()
        count = [0]
        lock = threading.Lock()

        def increment():
            with lock:
                count[0] += 1

        task = scheduler.schedule_repeating(0.1, increment)
        time.sleep(0.5)
        task.cancel()
        with lock:
            self.assertGreaterEqual(count[0], 3)

    def test_cancel_all(self):
        scheduler = SchedulerAPI()
        e1 = threading.Event()
        e2 = threading.Event()
        scheduler.schedule_once(10.0, e1.set)
        scheduler.schedule_once(10.0, e2.set)
        scheduler.cancel_all()
        self.assertFalse(e1.wait(timeout=0.5))
        self.assertFalse(e2.wait(timeout=0.5))

    def test_max_tasks_limit(self):
        scheduler = SchedulerAPI()
        tasks = []
        for _ in range(scheduler._MAX_TASKS):
            tasks.append(scheduler.schedule_once(60.0, lambda: None))
        with self.assertRaises(RuntimeError) as cm:
            scheduler.schedule_once(60.0, lambda: None)
        self.assertIn("task limit", str(cm.exception).lower())
        for t in tasks:
            t.cancel()

    def test_min_delay_enforced(self):
        scheduler = SchedulerAPI()
        called = threading.Event()
        task = scheduler.schedule_once(0.001, called.set)
        self.assertTrue(called.wait(timeout=2))
        task.cancel()

    def test_callback_exception_does_not_break_scheduler(self):
        scheduler = SchedulerAPI()
        called_after = threading.Event()
        scheduler.schedule_once(0.05, lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        scheduler.schedule_once(0.1, called_after.set)
        self.assertTrue(called_after.wait(timeout=2))

    def test_repeating_callback_exception_continues(self):
        scheduler = SchedulerAPI()
        count = [0]
        lock = threading.Lock()

        def bad_increment():
            with lock:
                count[0] += 1
            if count[0] == 1:
                raise RuntimeError("boom")

        task = scheduler.schedule_repeating(0.1, bad_increment)
        time.sleep(0.5)
        task.cancel()
        with lock:
            self.assertGreaterEqual(count[0], 2)

    def test_cancelled_task_removed_after_fire(self):
        scheduler = SchedulerAPI()
        called = threading.Event()
        scheduler.schedule_once(0.05, called.set)
        self.assertTrue(called.wait(timeout=2))
        time.sleep(0.1)
        with scheduler._lock:
            active = [t for t in scheduler._tasks if not t.is_cancelled]
        self.assertEqual(len(active), 0)


# ---------------------------------------------------------------------------
# _ScheduledTask
# ---------------------------------------------------------------------------

class TestScheduledTask(unittest.TestCase):

    def test_is_cancelled_default_false(self):
        task = _ScheduledTask(None)
        self.assertFalse(task.is_cancelled)

    def test_cancel_sets_flag(self):
        task = _ScheduledTask(None)
        task.cancel()
        self.assertTrue(task.is_cancelled)

    def test_cancel_cancels_timer(self):
        timer = threading.Timer(10, lambda: None)
        task = _ScheduledTask(timer)
        task.cancel()
        self.assertTrue(task.is_cancelled)

    def test_set_timer_after_cancel_does_not_set(self):
        task = _ScheduledTask(None)
        task.cancel()
        new_timer = threading.Timer(10, lambda: None)
        task.set_timer(new_timer)
        # Timer should be cancelled since task is already cancelled
        self.assertIsNone(task._timer)

    def test_set_timer_when_active(self):
        task = _ScheduledTask(None)
        new_timer = threading.Timer(10, lambda: None)
        task.set_timer(new_timer)
        self.assertIs(task._timer, new_timer)

    def test_repeating_flag(self):
        task = _ScheduledTask(None, repeating=True)
        self.assertTrue(task._repeating)

    def test_non_repeating_default(self):
        task = _ScheduledTask(None)
        self.assertFalse(task._repeating)

    def test_reschedule_fn_cleared_on_cancel(self):
        fn = MagicMock()
        task = _ScheduledTask(None, repeating=True, reschedule_fn=fn)
        self.assertIsNotNone(task._reschedule_fn)
        task.cancel()
        self.assertIsNone(task._reschedule_fn)

    def test_cancel_idempotent(self):
        task = _ScheduledTask(None)
        task.cancel()
        task.cancel()  # second cancel should not raise
        self.assertTrue(task.is_cancelled)


# ---------------------------------------------------------------------------
# HistoryAPI
# ---------------------------------------------------------------------------

class TestHistoryAPI(unittest.TestCase):

    def _make_event(self, latex="x^2", source="test"):
        return ClipboardEvent(
            created_at=datetime.now(timezone.utc),
            image_hash="hash_" + latex,
            image_width=100,
            image_height=100,
            latex=latex,
            source=source,
            status="ok",
        )

    def _make_api(self, *, latest_return=None, list_recent_return=None):
        if latest_return is None and list_recent_return is None:
            event = self._make_event()
            latest_return = event
            list_recent_return = [event]
        return HistoryAPI(
            latest_fn=MagicMock(return_value=latest_return),
            list_recent_fn=MagicMock(return_value=list_recent_return or []),
        )

    def test_latest_returns_event(self):
        event = self._make_event(latex="a+b")
        api = self._make_api(latest_return=event, list_recent_return=[event])
        result = api.latest()
        self.assertIsNotNone(result)
        self.assertEqual(result.latex, "a+b")

    def test_latest_returns_none_when_empty(self):
        api = self._make_api(latest_return=None, list_recent_return=[])
        self.assertIsNone(api.latest())

    def test_latest_delegates(self):
        fn = MagicMock(return_value=None)
        api = HistoryAPI(latest_fn=fn, list_recent_fn=MagicMock(return_value=[]))
        api.latest()
        fn.assert_called_once_with()

    def test_list_recent_default_limit(self):
        fn = MagicMock(return_value=[])
        api = HistoryAPI(latest_fn=MagicMock(return_value=None), list_recent_fn=fn)
        api.list_recent()
        fn.assert_called_once_with(20)

    def test_list_recent_custom_limit(self):
        fn = MagicMock(return_value=[])
        api = HistoryAPI(latest_fn=MagicMock(return_value=None), list_recent_fn=fn)
        api.list_recent(limit=5)
        fn.assert_called_once_with(5)

    def test_list_recent_returns_events(self):
        events = [self._make_event(latex=f"eq{i}") for i in range(3)]
        api = self._make_api(latest_return=events[0], list_recent_return=events)
        result = api.list_recent(limit=10)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0].latex, "eq0")
        self.assertEqual(result[2].latex, "eq2")

    def test_list_recent_empty(self):
        api = self._make_api(latest_return=None, list_recent_return=[])
        result = api.list_recent()
        self.assertEqual(len(result), 0)

    def test_latest_propagates_exception(self):
        api = HistoryAPI(
            latest_fn=MagicMock(side_effect=RuntimeError("db error")),
            list_recent_fn=MagicMock(return_value=[]),
        )
        with self.assertRaises(RuntimeError):
            api.latest()

    def test_list_recent_propagates_exception(self):
        api = HistoryAPI(
            latest_fn=MagicMock(return_value=None),
            list_recent_fn=MagicMock(side_effect=RuntimeError("db error")),
        )
        with self.assertRaises(RuntimeError):
            api.list_recent()

    def test_constructor_requires_keyword_args(self):
        with self.assertRaises(TypeError):
            HistoryAPI(MagicMock(), MagicMock())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ConfigAPI
# ---------------------------------------------------------------------------

class TestConfigAPI(unittest.TestCase):

    def _make_api(self, data=None):
        if data is None:
            data = {"threshold": 0.5, "name": "test"}
        return ConfigAPI(
            get_fn=MagicMock(side_effect=lambda k, d=None: data.get(k, d)),
            set_fn=MagicMock(side_effect=lambda k, v: data.__setitem__(k, v)),
            save_fn=MagicMock(),
            get_all_fn=MagicMock(return_value=dict(data)),
        )

    # -- get --

    def test_get_existing_key(self):
        api = self._make_api()
        self.assertEqual(api.get("threshold"), 0.5)

    def test_get_missing_key_returns_default(self):
        api = self._make_api()
        self.assertEqual(api.get("missing", "fallback"), "fallback")

    def test_get_missing_key_no_default_returns_none(self):
        api = self._make_api()
        self.assertIsNone(api.get("missing"))

    def test_get_delegates_with_key_and_default(self):
        fn = MagicMock(return_value=None)
        api = ConfigAPI(get_fn=fn, set_fn=MagicMock(), save_fn=MagicMock(), get_all_fn=MagicMock(return_value={}))
        api.get("key", default=42)
        fn.assert_called_once_with("key", 42)

    def test_get_none_value_in_store(self):
        data = {"key": None}
        api = self._make_api(data=data)
        # None is a valid stored value; default should NOT override it
        result = api.get("key", default="fallback")
        self.assertIsNone(result)

    # -- set --

    def test_set_delegates(self):
        api = self._make_api()
        api.set("new_key", "new_value")
        api._set.assert_called_once_with("new_key", "new_value")

    def test_set_overwrite_existing(self):
        api = self._make_api()
        api.set("threshold", 0.9)
        api._set.assert_called_once_with("threshold", 0.9)

    def test_set_various_types(self):
        api = self._make_api()
        api.set("int_key", 42)
        api.set("float_key", 3.14)
        api.set("bool_key", True)
        api.set("list_key", [1, 2, 3])
        api.set("none_key", None)
        self.assertEqual(api._set.call_count, 5)

    # -- save --

    def test_save_delegates(self):
        api = self._make_api()
        api.save()
        api._save.assert_called_once_with()

    def test_save_called_multiple_times(self):
        api = self._make_api()
        api.save()
        api.save()
        self.assertEqual(api._save.call_count, 2)

    # -- get_all --

    def test_get_all_returns_dict(self):
        api = self._make_api()
        result = api.get_all()
        self.assertIsInstance(result, dict)
        self.assertIn("threshold", result)
        self.assertIn("name", result)

    def test_get_all_empty(self):
        api = self._make_api(data={})
        result = api.get_all()
        self.assertEqual(result, {})

    # -- propagation --

    def test_get_propagates_exception(self):
        api = ConfigAPI(
            get_fn=MagicMock(side_effect=RuntimeError("config error")),
            set_fn=MagicMock(),
            save_fn=MagicMock(),
            get_all_fn=MagicMock(return_value={}),
        )
        with self.assertRaises(RuntimeError):
            api.get("key")

    def test_set_propagates_exception(self):
        api = ConfigAPI(
            get_fn=MagicMock(return_value=None),
            set_fn=MagicMock(side_effect=RuntimeError("config error")),
            save_fn=MagicMock(),
            get_all_fn=MagicMock(return_value={}),
        )
        with self.assertRaises(RuntimeError):
            api.set("key", "value")

    def test_save_propagates_exception(self):
        api = ConfigAPI(
            get_fn=MagicMock(return_value=None),
            set_fn=MagicMock(),
            save_fn=MagicMock(side_effect=OSError("disk full")),
            get_all_fn=MagicMock(return_value={}),
        )
        with self.assertRaises(OSError):
            api.save()

    # -- constructor keyword-only --

    def test_constructor_requires_keyword_args(self):
        with self.assertRaises(TypeError):
            ConfigAPI(MagicMock(), MagicMock(), MagicMock(), MagicMock())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# LoggerAPI
# ---------------------------------------------------------------------------

class TestLoggerAPI(unittest.TestCase):

    def test_get_returns_logger_with_prefix(self):
        api = LoggerAPI()
        logger = api.get("my_script")
        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "platex.script.my_script")

    def test_get_different_names_return_different_loggers(self):
        api = LoggerAPI()
        l1 = api.get("script1")
        l2 = api.get("script2")
        self.assertNotEqual(l1.name, l2.name)
        self.assertEqual(l1.name, "platex.script.script1")
        self.assertEqual(l2.name, "platex.script.script2")

    def test_get_same_name_returns_same_logger(self):
        api = LoggerAPI()
        l1 = api.get("my_script")
        l2 = api.get("my_script")
        self.assertIs(l1, l2)

    def test_get_empty_name(self):
        api = LoggerAPI()
        logger = api.get("")
        self.assertEqual(logger.name, "platex.script.")

    def test_get_with_dots(self):
        api = LoggerAPI()
        logger = api.get("sub.module")
        self.assertEqual(logger.name, "platex.script.sub.module")

    def test_get_returns_logging_logger(self):
        api = LoggerAPI()
        logger = api.get("test")
        # Verify it's a real logging.Logger that can be used
        self.assertTrue(hasattr(logger, "info"))
        self.assertTrue(hasattr(logger, "debug"))
        self.assertTrue(hasattr(logger, "warning"))
        self.assertTrue(hasattr(logger, "error"))

    def test_init_no_args(self):
        # LoggerAPI.__init__ takes no arguments
        api = LoggerAPI()
        self.assertIsNotNone(api)


# ---------------------------------------------------------------------------
# ScriptContext
# ---------------------------------------------------------------------------

class TestScriptContext(unittest.TestCase):

    def _make_clipboard(self):
        return ClipboardAPI(
            read_text_fn=MagicMock(return_value="text"),
            write_text_fn=MagicMock(),
            read_image_fn=MagicMock(return_value=None),
        )

    def _make_hotkeys(self):
        return HotkeyAPI(
            register_fn=MagicMock(return_value=True),
            unregister_fn=MagicMock(),
        )

    def _make_notifications(self):
        return NotificationAPI(
            show_fn=MagicMock(),
            show_ocr_fn=MagicMock(),
        )

    def _make_windows(self):
        return WindowAPI(get_foreground_title_fn=MagicMock(return_value="Window"))

    def _make_mouse(self):
        return MouseAPI(click_fn=MagicMock())

    def _make_scheduler(self):
        return SchedulerAPI()

    def _make_history(self):
        return HistoryAPI(
            latest_fn=MagicMock(return_value=None),
            list_recent_fn=MagicMock(return_value=[]),
        )

    def _make_config(self):
        return ConfigAPI(
            get_fn=MagicMock(return_value=None),
            set_fn=MagicMock(),
            save_fn=MagicMock(),
            get_all_fn=MagicMock(return_value={}),
        )

    def _make_logger(self):
        return LoggerAPI()

    def _make_context(self):
        return ScriptContext(
            clipboard=self._make_clipboard(),
            hotkeys=self._make_hotkeys(),
            notifications=self._make_notifications(),
            windows=self._make_windows(),
            mouse=self._make_mouse(),
            scheduler=self._make_scheduler(),
            history=self._make_history(),
            config=self._make_config(),
            logger=self._make_logger(),
        )

    # -- attribute presence --

    def test_has_clipboard(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.clipboard, ClipboardAPI)

    def test_has_hotkeys(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.hotkeys, HotkeyAPI)

    def test_has_notifications(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.notifications, NotificationAPI)

    def test_has_windows(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.windows, WindowAPI)

    def test_has_mouse(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.mouse, MouseAPI)

    def test_has_scheduler(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.scheduler, SchedulerAPI)

    def test_has_history(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.history, HistoryAPI)

    def test_has_config(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.config, ConfigAPI)

    def test_has_logger(self):
        ctx = self._make_context()
        self.assertIsInstance(ctx.logger, LoggerAPI)

    # -- shutdown --

    def test_shutdown_cancels_scheduler_tasks(self):
        ctx = self._make_context()
        called = threading.Event()
        ctx.scheduler.schedule_once(10.0, called.set)
        ctx.shutdown()
        self.assertFalse(called.wait(timeout=0.5))

    def test_shutdown_cancels_multiple_tasks(self):
        ctx = self._make_context()
        e1 = threading.Event()
        e2 = threading.Event()
        ctx.scheduler.schedule_once(10.0, e1.set)
        ctx.scheduler.schedule_once(10.0, e2.set)
        ctx.shutdown()
        self.assertFalse(e1.wait(timeout=0.5))
        self.assertFalse(e2.wait(timeout=0.5))

    def test_shutdown_idempotent(self):
        ctx = self._make_context()
        ctx.shutdown()
        ctx.shutdown()  # second call should not raise

    # -- API delegation through context --

    def test_clipboard_read_text_through_context(self):
        ctx = self._make_context()
        result = ctx.clipboard.read_text()
        self.assertEqual(result, "text")

    def test_clipboard_write_text_through_context(self):
        ctx = self._make_context()
        ctx.clipboard.write_text("new text")
        ctx.clipboard._write_text.assert_called_once_with("new text")

    def test_hotkeys_register_through_context(self):
        ctx = self._make_context()
        result = ctx.hotkeys.register("Ctrl+A", lambda: None)
        self.assertTrue(result)

    def test_hotkeys_unregister_through_context(self):
        ctx = self._make_context()
        ctx.hotkeys.unregister("Ctrl+A")
        ctx.hotkeys._unregister.assert_called_once_with("Ctrl+A")

    def test_notifications_show_through_context(self):
        ctx = self._make_context()
        ctx.notifications.show("Title", "Msg")
        ctx.notifications._show.assert_called_once_with("Title", "Msg", 5000)

    def test_notifications_show_ocr_through_context(self):
        ctx = self._make_context()
        ctx.notifications.show_ocr_result("x^2")
        ctx.notifications._show_ocr.assert_called_once_with("x^2", 12000)

    def test_windows_get_title_through_context(self):
        ctx = self._make_context()
        self.assertEqual(ctx.windows.get_foreground_title(), "Window")

    def test_mouse_click_through_context(self):
        ctx = self._make_context()
        ctx.mouse.click(100, 200)
        ctx.mouse._click.assert_called_once_with(100, 200, "left")

    def test_history_latest_through_context(self):
        ctx = self._make_context()
        self.assertIsNone(ctx.history.latest())

    def test_history_list_recent_through_context(self):
        ctx = self._make_context()
        result = ctx.history.list_recent(limit=5)
        self.assertEqual(result, [])

    def test_config_get_through_context(self):
        ctx = self._make_context()
        ctx.config.get("key")
        ctx.config._get.assert_called_once_with("key", None)

    def test_config_set_through_context(self):
        ctx = self._make_context()
        ctx.config.set("key", "value")
        ctx.config._set.assert_called_once_with("key", "value")

    def test_config_save_through_context(self):
        ctx = self._make_context()
        ctx.config.save()
        ctx.config._save.assert_called_once()

    def test_config_get_all_through_context(self):
        ctx = self._make_context()
        result = ctx.config.get_all()
        self.assertEqual(result, {})

    def test_logger_get_through_context(self):
        ctx = self._make_context()
        logger = ctx.logger.get("test")
        self.assertEqual(logger.name, "platex.script.test")

    # -- constructor keyword-only --

    def test_constructor_requires_keyword_args(self):
        with self.assertRaises(TypeError):
            ScriptContext(
                self._make_clipboard(),
                self._make_hotkeys(),
                self._make_notifications(),
                self._make_windows(),
                self._make_mouse(),
                self._make_scheduler(),
                self._make_history(),
                self._make_config(),
                self._make_logger(),
            )  # type: ignore[arg-type]

    # -- constructor stores references (not copies) --

    def test_stores_clipboard_reference(self):
        clipboard = self._make_clipboard()
        ctx = ScriptContext(
            clipboard=clipboard,
            hotkeys=self._make_hotkeys(),
            notifications=self._make_notifications(),
            windows=self._make_windows(),
            mouse=self._make_mouse(),
            scheduler=self._make_scheduler(),
            history=self._make_history(),
            config=self._make_config(),
            logger=self._make_logger(),
        )
        self.assertIs(ctx.clipboard, clipboard)

    def test_stores_scheduler_reference(self):
        scheduler = self._make_scheduler()
        ctx = ScriptContext(
            clipboard=self._make_clipboard(),
            hotkeys=self._make_hotkeys(),
            notifications=self._make_notifications(),
            windows=self._make_windows(),
            mouse=self._make_mouse(),
            scheduler=scheduler,
            history=self._make_history(),
            config=self._make_config(),
            logger=self._make_logger(),
        )
        self.assertIs(ctx.scheduler, scheduler)


# ---------------------------------------------------------------------------
# Integration: end-to-end workflow
# ---------------------------------------------------------------------------

class TestScriptContextIntegration(unittest.TestCase):
    """Integration tests that exercise multiple APIs together."""

    def test_schedule_and_shutdown_workflow(self):
        ctx = ScriptContext(
            clipboard=ClipboardAPI(
                read_text_fn=MagicMock(return_value=None),
                write_text_fn=MagicMock(),
                read_image_fn=MagicMock(return_value=None),
            ),
            hotkeys=HotkeyAPI(
                register_fn=MagicMock(return_value=True),
                unregister_fn=MagicMock(),
            ),
            notifications=NotificationAPI(
                show_fn=MagicMock(),
                show_ocr_fn=MagicMock(),
            ),
            windows=WindowAPI(get_foreground_title_fn=MagicMock(return_value="")),
            mouse=MouseAPI(click_fn=MagicMock()),
            scheduler=SchedulerAPI(),
            history=HistoryAPI(
                latest_fn=MagicMock(return_value=None),
                list_recent_fn=MagicMock(return_value=[]),
            ),
            config=ConfigAPI(
                get_fn=MagicMock(return_value=None),
                set_fn=MagicMock(),
                save_fn=MagicMock(),
                get_all_fn=MagicMock(return_value={}),
            ),
            logger=LoggerAPI(),
        )

        # Schedule a task that uses clipboard
        def write_to_clipboard():
            ctx.clipboard.write_text("scheduled text")

        task = ctx.scheduler.schedule_once(0.05, write_to_clipboard)
        time.sleep(0.3)
        ctx.clipboard._write_text.assert_called_once_with("scheduled text")

        # Schedule another and then shutdown
        ctx.scheduler.schedule_once(60.0, lambda: None)
        ctx.shutdown()

    def test_hotkey_triggers_notification(self):
        """Simulate a hotkey callback that shows a notification."""
        show_fn = MagicMock()
        ctx = ScriptContext(
            clipboard=ClipboardAPI(
                read_text_fn=MagicMock(return_value=None),
                write_text_fn=MagicMock(),
                read_image_fn=MagicMock(return_value=None),
            ),
            hotkeys=HotkeyAPI(
                register_fn=MagicMock(return_value=True),
                unregister_fn=MagicMock(),
            ),
            notifications=NotificationAPI(
                show_fn=show_fn,
                show_ocr_fn=MagicMock(),
            ),
            windows=WindowAPI(get_foreground_title_fn=MagicMock(return_value="")),
            mouse=MouseAPI(click_fn=MagicMock()),
            scheduler=SchedulerAPI(),
            history=HistoryAPI(
                latest_fn=MagicMock(return_value=None),
                list_recent_fn=MagicMock(return_value=[]),
            ),
            config=ConfigAPI(
                get_fn=MagicMock(return_value=None),
                set_fn=MagicMock(),
                save_fn=MagicMock(),
                get_all_fn=MagicMock(return_value={}),
            ),
            logger=LoggerAPI(),
        )

        # Simulate: register a hotkey that shows a notification
        captured_callback = None

        def capture_register(hotkey, callback):
            nonlocal captured_callback
            captured_callback = callback
            return True

        ctx.hotkeys._register = capture_register
        ctx.hotkeys.register("Ctrl+Shift+N", lambda: ctx.notifications.show("Hotkey", "Triggered"))

        # Simulate hotkey press
        if captured_callback:
            captured_callback()

        show_fn.assert_called_once_with("Hotkey", "Triggered", 5000)
        ctx.shutdown()


if __name__ == "__main__":
    unittest.main()
