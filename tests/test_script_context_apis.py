from __future__ import annotations

import logging
import unittest

from platex_client.script_context import (
    ClipboardAPI,
    HotkeyAPI,
    NotificationAPI,
    WindowAPI,
    MouseAPI,
    HistoryAPI,
    ConfigAPI,
    LoggerAPI,
    ScriptContext,
    SchedulerAPI,
)


class TestClipboardAPI(unittest.TestCase):
    def test_read_text(self):
        api = ClipboardAPI(
            read_text_fn=lambda: "hello",
            write_text_fn=lambda t: None,
            read_image_fn=lambda: None,
        )
        self.assertEqual(api.read_text(), "hello")

    def test_read_text_none(self):
        api = ClipboardAPI(
            read_text_fn=lambda: None,
            write_text_fn=lambda t: None,
            read_image_fn=lambda: None,
        )
        self.assertIsNone(api.read_text())

    def test_write_text(self):
        written = []
        api = ClipboardAPI(
            read_text_fn=lambda: None,
            write_text_fn=lambda t: written.append(t),
            read_image_fn=lambda: None,
        )
        api.write_text("test")
        self.assertEqual(written, ["test"])

    def test_read_image_none(self):
        api = ClipboardAPI(
            read_text_fn=lambda: None,
            write_text_fn=lambda t: None,
            read_image_fn=lambda: None,
        )
        self.assertIsNone(api.read_image())

    def test_read_image_returns_value(self):
        from platex_client.models import ClipboardImage
        img = ClipboardImage(image_bytes=b"fake", width=10, height=10)
        api = ClipboardAPI(
            read_text_fn=lambda: None,
            write_text_fn=lambda t: None,
            read_image_fn=lambda: img,
        )
        self.assertIs(api.read_image(), img)


class TestHotkeyAPI(unittest.TestCase):
    def test_register_success(self):
        api = HotkeyAPI(
            register_fn=lambda h, cb: True,
            unregister_fn=lambda h: None,
        )
        self.assertTrue(api.register("Ctrl+K", lambda: None))

    def test_register_failure(self):
        api = HotkeyAPI(
            register_fn=lambda h, cb: False,
            unregister_fn=lambda h: None,
        )
        self.assertFalse(api.register("Ctrl+K", lambda: None))

    def test_unregister(self):
        unregistered = []
        api = HotkeyAPI(
            register_fn=lambda h, cb: True,
            unregister_fn=lambda h: unregistered.append(h),
        )
        api.unregister("Ctrl+K")
        self.assertEqual(unregistered, ["Ctrl+K"])


class TestNotificationAPI(unittest.TestCase):
    def test_show(self):
        calls = []
        api = NotificationAPI(
            show_fn=lambda t, m, ms: calls.append((t, m, ms)),
            show_ocr_fn=lambda l, ms: None,
        )
        api.show("Title", "Message")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "Title")
        self.assertEqual(calls[0][1], "Message")
        self.assertEqual(calls[0][2], 5000)

    def test_show_custom_timeout(self):
        calls = []
        api = NotificationAPI(
            show_fn=lambda t, m, ms: calls.append(ms),
            show_ocr_fn=lambda l, ms: None,
        )
        api.show("Title", "Message", timeout_ms=10000)
        self.assertEqual(calls, [10000])

    def test_show_ocr_result(self):
        calls = []
        api = NotificationAPI(
            show_fn=lambda t, m, ms: None,
            show_ocr_fn=lambda l, ms: calls.append((l, ms)),
        )
        api.show_ocr_result(r"x^2")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], r"x^2")
        self.assertEqual(calls[0][1], 12000)

    def test_show_ocr_result_custom_timeout(self):
        calls = []
        api = NotificationAPI(
            show_fn=lambda t, m, ms: None,
            show_ocr_fn=lambda l, ms: calls.append(ms),
        )
        api.show_ocr_result(r"x^2", timeout_ms=5000)
        self.assertEqual(calls, [5000])


class TestWindowAPI(unittest.TestCase):
    def test_get_foreground_title(self):
        api = WindowAPI(get_foreground_title_fn=lambda: "Test Window")
        self.assertEqual(api.get_foreground_title(), "Test Window")

    def test_get_foreground_title_empty(self):
        api = WindowAPI(get_foreground_title_fn=lambda: "")
        self.assertEqual(api.get_foreground_title(), "")


class TestMouseAPI(unittest.TestCase):
    def test_click(self):
        clicks = []
        api = MouseAPI(click_fn=lambda x, y, b: clicks.append((x, y, b)))
        api.click(500, 300)
        self.assertEqual(clicks, [(500, 300, "left")])

    def test_click_right_button(self):
        clicks = []
        api = MouseAPI(click_fn=lambda x, y, b: clicks.append((x, y, b)))
        api.click(100, 200, button="right")
        self.assertEqual(clicks, [(100, 200, "right")])


class TestHistoryAPI(unittest.TestCase):
    def test_latest(self):
        from platex_client.models import ClipboardEvent
        event = ClipboardEvent(
            created_at=None, image_hash="h", image_width=10, image_height=10,
            latex="x", source="s", status="ok",
        )
        api = HistoryAPI(latest_fn=lambda: event, list_recent_fn=lambda n: [event])
        self.assertIs(api.latest(), event)

    def test_latest_none(self):
        api = HistoryAPI(latest_fn=lambda: None, list_recent_fn=lambda n: [])
        self.assertIsNone(api.latest())

    def test_list_recent_default_limit(self):
        api = HistoryAPI(latest_fn=lambda: None, list_recent_fn=lambda n: [n])
        result = api.list_recent()
        self.assertEqual(result, [20])

    def test_list_recent_custom_limit(self):
        api = HistoryAPI(latest_fn=lambda: None, list_recent_fn=lambda n: [n])
        result = api.list_recent(limit=50)
        self.assertEqual(result, [50])


class TestConfigAPI(unittest.TestCase):
    def test_get(self):
        api = ConfigAPI(
            get_fn=lambda k, d: "value" if k == "key" else d,
            set_fn=lambda k, v: None,
            save_fn=lambda: None,
            get_all_fn=lambda: {},
        )
        self.assertEqual(api.get("key"), "value")
        self.assertEqual(api.get("missing", "default"), "default")

    def test_set(self):
        sets = []
        api = ConfigAPI(
            get_fn=lambda k, d: d,
            set_fn=lambda k, v: sets.append((k, v)),
            save_fn=lambda: None,
            get_all_fn=lambda: {},
        )
        api.set("key", "value")
        self.assertEqual(sets, [("key", "value")])

    def test_save(self):
        saved = [False]
        api = ConfigAPI(
            get_fn=lambda k, d: d,
            set_fn=lambda k, v: None,
            save_fn=lambda: saved.__setitem__(0, True),
            get_all_fn=lambda: {},
        )
        api.save()
        self.assertTrue(saved[0])

    def test_get_all(self):
        api = ConfigAPI(
            get_fn=lambda k, d: d,
            set_fn=lambda k, v: None,
            save_fn=lambda: None,
            get_all_fn=lambda: {"key": "value"},
        )
        self.assertEqual(api.get_all(), {"key": "value"})


class TestLoggerAPI(unittest.TestCase):
    def test_get_returns_logger(self):
        api = LoggerAPI()
        logger = api.get("my_script")
        self.assertIsInstance(logger, logging.Logger)
        self.assertIn("platex.script.my_script", logger.name)

    def test_get_different_names(self):
        api = LoggerAPI()
        logger1 = api.get("script1")
        logger2 = api.get("script2")
        self.assertNotEqual(logger1.name, logger2.name)


class TestScriptContext(unittest.TestCase):
    def _make_context(self):
        return ScriptContext(
            clipboard=ClipboardAPI(
                read_text_fn=lambda: None,
                write_text_fn=lambda t: None,
                read_image_fn=lambda: None,
            ),
            hotkeys=HotkeyAPI(
                register_fn=lambda h, cb: True,
                unregister_fn=lambda h: None,
            ),
            notifications=NotificationAPI(
                show_fn=lambda t, m, ms: None,
                show_ocr_fn=lambda l, ms: None,
            ),
            windows=WindowAPI(get_foreground_title_fn=lambda: ""),
            mouse=MouseAPI(click_fn=lambda x, y, b: None),
            scheduler=SchedulerAPI(),
            history=HistoryAPI(latest_fn=lambda: None, list_recent_fn=lambda n: []),
            config=ConfigAPI(
                get_fn=lambda k, d: d,
                set_fn=lambda k, v: None,
                save_fn=lambda: None,
                get_all_fn=lambda: {},
            ),
            logger=LoggerAPI(),
        )

    def test_context_has_all_apis(self):
        ctx = self._make_context()
        self.assertIsNotNone(ctx.clipboard)
        self.assertIsNotNone(ctx.hotkeys)
        self.assertIsNotNone(ctx.notifications)
        self.assertIsNotNone(ctx.windows)
        self.assertIsNotNone(ctx.mouse)
        self.assertIsNotNone(ctx.scheduler)
        self.assertIsNotNone(ctx.history)
        self.assertIsNotNone(ctx.config)
        self.assertIsNotNone(ctx.logger)

    def test_shutdown_cancels_scheduler(self):
        ctx = self._make_context()
        fired = __import__("threading").Event()
        ctx.scheduler.schedule_once(10.0, fired.set)
        ctx.shutdown()
        self.assertFalse(fired.wait(timeout=0.1))

    def test_clipboard_via_context(self):
        ctx = self._make_context()
        self.assertIsNone(ctx.clipboard.read_text())

    def test_windows_via_context(self):
        ctx = self._make_context()
        self.assertEqual(ctx.windows.get_foreground_title(), "")


if __name__ == "__main__":
    unittest.main()
