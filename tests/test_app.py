from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from platex_client.app_state import AppState
from platex_client.app import PlatexApp
from platex_client.config import ConfigStore
from platex_client.events import reset_event_bus
from platex_client.secrets import clear_all


class TestPlatexAppCreation(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_create_app(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=Path(temp_dir) / "test_script.py",
            )
            self.assertEqual(app.state, AppState.IDLE)
            self.assertFalse(app.is_running)

    def test_default_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=Path(temp_dir) / "test_script.py",
            )
            self.assertEqual(app.interval, 0.8)

    def test_custom_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=Path(temp_dir) / "test_script.py",
                interval=2.0,
            )
            self.assertEqual(app.interval, 2.0)

    def test_isolate_mode_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=Path(temp_dir) / "test_script.py",
            )
            self.assertFalse(app.isolate_mode)

    def test_isolate_mode_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=Path(temp_dir) / "test_script.py",
                isolate_mode=True,
            )
            self.assertTrue(app.isolate_mode)


class TestPlatexAppStartStop(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def _make_app(self, temp_dir):
        script_path = Path(temp_dir) / "test_script.py"
        script_path.write_text(
            "def process_image(image_bytes, context):\n    return 'test'\n",
            encoding="utf-8",
        )
        return PlatexApp(
            db_path=Path(temp_dir) / "test.sqlite3",
            script_path=script_path,
            interval=0.8,
        )

    def test_start_transitions_to_running(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._make_app(temp_dir)
            app.start()
            try:
                self.assertTrue(app.is_running)
            finally:
                app.stop()

    def test_stop_transitions_to_stopped(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._make_app(temp_dir)
            app.start()
            app.stop()
            self.assertTrue(app.state in (AppState.STOPPED, AppState.IDLE))

    def test_start_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._make_app(temp_dir)
            app.start()
            app.start()
            try:
                self.assertTrue(app.is_running)
            finally:
                app.stop()

    def test_stop_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._make_app(temp_dir)
            app.stop()
            app.stop()

    def test_start_stop_cycle(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = self._make_app(temp_dir)
            app.start()
            self.assertTrue(app.is_running)
            app.stop()
            self.assertTrue(app.state in (AppState.STOPPED, AppState.IDLE))

    def test_start_isolate_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=Path(temp_dir) / "test_script.py",
                isolate_mode=True,
            )
            Path(temp_dir, "test_script.py").write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            app.start()
            try:
                self.assertTrue(app.is_running)
            finally:
                app.stop()


class TestPlatexAppSetWatcherPublishing(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()

    def test_set_publishing_no_watcher(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=Path(temp_dir) / "test_script.py",
            )
            app.set_watcher_publishing(True)
            app.set_watcher_publishing(False)


class TestPlatexAppSetExternalHistory(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()

    def test_set_external_history(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            from platex_client.history import HistoryStore
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=Path(temp_dir) / "test_script.py",
            )
            history = HistoryStore(Path(temp_dir) / "ext.sqlite3")
            app.set_external_history(history)
            self.assertIs(app._external_history, history)
            history.close()


class TestPlatexAppRestartWatcher(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()
        for key in ("GLM_API_KEY", "GLM_MODEL", "GLM_BASE_URL"):
            os.environ.pop(key, None)

    def test_restart_with_new_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=script_path,
                interval=0.8,
            )
            app.restart_watcher(interval=2.0)
            self.assertEqual(app.interval, 2.0)
            app.stop()

    def test_restart_with_isolate_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=script_path,
            )
            app.restart_watcher(isolate_mode=True)
            self.assertTrue(app.isolate_mode)
            app.stop()

    def test_restart_clamps_small_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=script_path,
            )
            app.restart_watcher(interval=0.001)
            self.assertGreaterEqual(app.interval, 0.1)
            app.stop()

    def test_restart_clamps_large_interval(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            app = PlatexApp(
                db_path=Path(temp_dir) / "test.sqlite3",
                script_path=script_path,
            )
            app.restart_watcher(interval=100.0)
            self.assertLessEqual(app.interval, 60.0)
            app.stop()


class TestPlatexAppRunOnce(unittest.TestCase):
    def setUp(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()

    def tearDown(self):
        ConfigStore.reset()
        clear_all()
        reset_event_bus()

    def test_run_once_no_clipboard_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "test_script.py"
            script_path.write_text(
                "def process_image(image_bytes, context):\n    return 'test'\n",
                encoding="utf-8",
            )
            db_path = Path(temp_dir) / "test2.sqlite3"
            app = PlatexApp(
                db_path=db_path,
                script_path=script_path,
            )
            try:
                with patch("platex_client.watcher.grab_image_clipboard", return_value=None):
                    result = app.run_once()
                self.assertIsNone(result)
            finally:
                if app._watcher is not None:
                    app._watcher.close()
                    app._watcher = None


if __name__ == "__main__":
    unittest.main()
