from __future__ import annotations

import base64
import logging
import os
import queue
import re
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .app import PlatexApp
from .clipboard import copy_text_to_clipboard
from .config import default_config_path
from .config_manager import ConfigManager, get_config_dir, set_config_dir, config_file_path
from .events import EventBus, OcrSuccessEvent, ShowPanelEvent, ShutdownRequestEvent, get_event_bus
from .history import HistoryStore
from .i18n import t, on_language_changed
from .models import ClipboardEvent
from .platform_utils import is_startup_enabled, release_single_instance_lock, set_startup_enabled, startup_command, KERNEL32
from .popup_manager import PopupManager


_INSTANCE_PANEL_EVENT_NAME = r"Local\PLatexClient_ShowControlPanel"

if sys.platform == "win32":
    _EVENT_MODIFY_STATE = 0x0002
    _SYNCHRONIZE = 0x00100000
    _INFINITE = 0xFFFFFFFF


def _load_pystray():
    try:
        import pystray
        from pystray import Menu, MenuItem
    except ImportError as exc:
        raise RuntimeError("pystray is required for tray mode. Install project dependencies first.") from exc

    return pystray, Menu, MenuItem


def _build_icon_image():
    import sys

    from PIL import Image

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
        candidates.append(base / "assets" / "platex-client.png")
        candidates.append(base / "assets" / "platex-client.ico")
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "assets" / "platex-client.png")
        candidates.append(exe_dir / "assets" / "platex-client.ico")
    else:
        here = Path(__file__).resolve().parent.parent.parent
        candidates.append(here / "assets" / "platex-client.png")
        candidates.append(here / "assets" / "platex-client.ico")

    for p in candidates:
        if p.exists():
            with Image.open(p) as img:
                return img.convert("RGBA").resize((64, 64), Image.LANCZOS)

    from PIL import ImageDraw

    image = Image.new("RGBA", (64, 64), (28, 28, 46, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, outline=(123, 162, 212, 255), width=3)
    draw.line((18, 22, 18, 42), fill=(123, 162, 212, 255), width=4)
    draw.line((46, 22, 46, 42), fill=(123, 162, 212, 255), width=4)
    draw.line((18, 42, 32, 30), fill=(123, 162, 212, 255), width=4)
    draw.line((32, 30, 46, 42), fill=(123, 162, 212, 255), width=4)
    return image


def _panel_config_path() -> Path:
    preferred = config_file_path()
    preferred.parent.mkdir(parents=True, exist_ok=True)
    if preferred.exists():
        return preferred

    cwd = Path.cwd()
    legacy_candidates = [
        cwd / "config.yaml",
        cwd / "config.example.yaml",
    ]
    legacy = next((candidate for candidate in legacy_candidates if candidate.exists()), None)
    if legacy is not None:
        try:
            preferred.write_text(legacy.read_text(encoding="utf-8"), encoding="utf-8")
            return preferred
        except Exception:
            return legacy

    return preferred


def _validate_script_path_safety(script_path: Path) -> Path:
    resolved = script_path.resolve()
    if script_path.is_symlink():
        raise ValueError(f"Script path is a symlink (not allowed): {script_path} -> {resolved}")
    if ".." in script_path.parts:
        raise ValueError(f"Script path contains '..' segments (not allowed): {script_path}")
    if not resolved.is_file():
        raise ValueError(f"Script path is not a regular file: {resolved}")
    return resolved


def _load_panel_config(default_script: Path) -> dict[str, Any]:
    from .config import load_config

    cfg = load_config()
    active_script = str(cfg.script) if cfg.script else str(default_script)
    if not active_script or not Path(active_script).exists():
        active_script = str(default_script)

    return {
        "db_path": str(cfg.db_path) if cfg.db_path else "",
        "script": active_script,
        "log_file": str(cfg.log_file) if cfg.log_file else "",
        "interval": cfg.interval,
        "isolate_mode": cfg.isolate_mode,
        "glm_api_key": cfg.glm_api_key or "",
        "glm_model": cfg.glm_model or "",
        "glm_base_url": cfg.glm_base_url or "",
        "auto_start": cfg.auto_start,
        "ui_language": cfg.ui_language,
        "language_pack": cfg.language_pack,
        "scripts": {},
    }


def _save_panel_config(payload: dict[str, Any]) -> None:
    from .config import ConfigStore
    store = ConfigStore.instance()
    store.request_update_and_save(payload)


def _ensure_scripts_in_config(script_configs: dict[str, dict[str, Any]]) -> None:
    path = _panel_config_path()
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}
    if "scripts" not in payload:
        payload["scripts"] = script_configs
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        logger.info("Added scripts section to config file")


_UNSAFE_PS_CHARS = re.compile(r"[`$|;&{}()!@#~%+\x00-\x1f\"<>]")


def _sanitize_path_for_ps(path_str: str) -> str:
    path_obj = Path(path_str).resolve()
    resolved = str(path_obj)
    if _UNSAFE_PS_CHARS.search(resolved):
        raise ValueError(f"Path contains unsafe characters for shell use: {resolved}")
    if "'" in resolved:
        raise ValueError(f"Path contains single quotes which cannot be safely escaped for shell use: {resolved}")
    return resolved


def _open_runtime_terminal(script_path: Path, log_path: str | None) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Open terminal is currently supported on Windows only.")

    workdir = script_path.parent if script_path.exists() else Path.cwd()
    log_file = Path(log_path).expanduser() if log_path else None

    try:
        safe_workdir = _sanitize_path_for_ps(str(workdir))
    except ValueError as exc:
        logger.error("Unsafe workdir path rejected: %s", exc)
        return

    ps_lines = [
        f"Set-Location -LiteralPath '{safe_workdir}'",
        "Write-Host 'PLatex runtime terminal' -ForegroundColor Cyan",
        "Write-Host 'You can run: .\\platex-client.exe logs --limit 200' -ForegroundColor DarkGray",
    ]
    if log_file is not None:
        try:
            safe_log = _sanitize_path_for_ps(str(log_file))
        except ValueError as exc:
            logger.error("Unsafe log path rejected: %s", exc)
            safe_log = None
        if safe_log is not None:
            ps_lines.extend(
                [
                    "Write-Host ''",
                    f"Write-Host 'Tailing log: {safe_log}' -ForegroundColor Green",
                    f"Get-Content -LiteralPath '{safe_log}' -Tail 50",
                ]
            )

    command = "; ".join(ps_lines)
    encoded_command = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    subprocess.Popen(
        ["powershell.exe", "-NoExit", "-EncodedCommand", encoded_command],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _create_instance_panel_event():
    if sys.platform != "win32":
        return None

    handle = KERNEL32.CreateEventW(None, False, False, _INSTANCE_PANEL_EVENT_NAME)
    if not handle:
        return None
    return handle


logger = logging.getLogger("platex.tray")


@dataclass(slots=True)
class TrayController:
    app: PlatexApp
    history: HistoryStore

    @staticmethod
    def _limit_title(text: str, limit: int = 120) -> str:
        text = text.replace("\n", " ").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1] + "…"

    def run(self, *, open_panel_on_start: bool = False) -> int:
        pystray, Menu, MenuItem = _load_pystray()
        previous_sigint_handler = signal.getsignal(signal.SIGINT)

        private_cfg = _load_panel_config(self.app.script_path)
        active_script_raw = private_cfg.get("script")
        active_script = Path(active_script_raw) if isinstance(active_script_raw, str) and active_script_raw else self.app.script_path
        try:
            active_script = _validate_script_path_safety(active_script)
        except ValueError as exc:
            logger.warning("Script path from config rejected: %s. Falling back to default.", exc)
            active_script = self.app.script_path
        if active_script.exists():
            self.app.script_path = active_script

        startup_script_configs = private_cfg.get("scripts") if isinstance(private_cfg.get("scripts"), dict) else {}

        popup_manager = PopupManager()
        panel_event_handle = _create_instance_panel_event()

        def popup_loop() -> None:
            logger.info("Starting popup_loop")
            os.environ.setdefault("QT_OPENGL", "software")
            os.environ.setdefault("QT_QUICK_BACKEND", "software")
            try:
                from PyQt6.QtCore import QTimer, Qt
                from PyQt6.QtWidgets import QApplication
            except Exception as exc:
                logger.exception("PyQt popup unavailable: %s", exc)
                popup_manager.request_shutdown()
                return

            logger.info("PyQt6 imported successfully, creating QApplication")
            app = QApplication.instance()
            if app is None:
                try:
                    app = QApplication([])
                except Exception as exc:
                    logger.exception("Failed to create QApplication: %s", exc)
                    popup_manager.request_shutdown()
                    return
            logger.info("QApplication ready, setting up event loop")
            app.setQuitOnLastWindowClosed(False)

            def _qt_exception_handler(exc_type, exc_value, exc_tb):
                logger.critical("Unhandled exception in Qt event loop: %s: %s", exc_type.__name__, exc_value, exc_info=(exc_type, exc_value, exc_tb))

            import traceback
            original_excepthook = sys.excepthook
            sys.excepthook = _qt_exception_handler

            from .ui.popup import Popup
            from .ui.control_panel import ControlPanel

            panel_window = None
            active_popups = []
            active_popups_lock = threading.RLock()
            _MAX_ACTIVE_POPUPS = 10

            def _clear_panel_ref(_obj=None) -> None:
                nonlocal panel_window
                panel_window = None

            def _handle_panel_commands() -> None:
                nonlocal panel_window
                while True:
                    try:
                        panel_cmd = popup_manager.panel_queue.get_nowait()
                    except queue.Empty:
                        break

                    if panel_cmd == "open-panel":
                        logger.info("Received open-panel command")
                        if panel_window is None or not panel_window.isVisible():
                            logger.info("Creating new control panel window")
                            panel_window = ControlPanel(controller_ref=self)
                            panel_window.destroyed.connect(_clear_panel_ref)
                            panel_window.show()
                            logger.info("Control panel window shown")
                        else:
                            logger.info("Raising existing control panel window")
                            panel_window.raise_()
                            panel_window.activateWindow()

            def _pump_messages() -> None:
                _handle_panel_commands()
                while True:
                    try:
                        item = popup_manager.popup_queue.get_nowait()
                    except queue.Empty:
                        break

                    if item is None:
                        popup_manager.confirm_shutdown()
                        app.quit()
                        return

                    try:
                        title, latex, timeout_ms = item
                        preview = latex.replace("\n", " ").strip()
                        if len(preview) > 220:
                            preview = preview[:217] + "..."
                        message = f"{preview or t('tray_ocr_completed')}{t('tray_popup_click_to_copy')}"

                        popup = Popup(title, message, latex)
                        screen = app.primaryScreen()
                        if screen is not None:
                            available = screen.availableGeometry()
                            x = max(available.left() + 8, available.right() - popup.width() - 20)
                            y = available.top() + 24
                            popup.move(x, y)

                        popup.setWindowOpacity(1.0)
                        popup.show()
                        popup.raise_()
                        popup.start_auto_fade(timeout_ms)
                        to_close = []
                        with active_popups_lock:
                            while len(active_popups) >= _MAX_ACTIVE_POPUPS:
                                oldest = active_popups.pop(0)
                                to_close.append(oldest)
                            active_popups.append(popup)
                        for old_popup in to_close:
                            try:
                                old_popup.close()
                            except Exception:
                                pass

                        def _release_popup_ref(_obj=None, *, _popup=popup) -> None:
                            with active_popups_lock:
                                try:
                                    active_popups.remove(_popup)
                                except ValueError:
                                    pass

                        popup.destroyed.connect(_release_popup_ref)
                    except Exception:
                        logger.exception("Error creating/showing popup, skipping")

            pump_timer = QTimer()
            pump_timer.setInterval(16)
            pump_timer.timeout.connect(_pump_messages)
            pump_timer.start()

            logger.info("Starting Qt event loop (app.exec)")
            app.exec()
            logger.info("Qt event loop exited")
            sys.excepthook = original_excepthook

        def _panel_signal_loop() -> None:
            if panel_event_handle is None:
                return
            while not popup_manager.stop_event.is_set():
                result = KERNEL32.WaitForSingleObject(panel_event_handle, 250)
                if result == 0 and not popup_manager.stop_event.is_set():
                    popup_manager.panel_queue.put("open-panel")

        panel_signal_thread = threading.Thread(target=_panel_signal_loop, name="platex-panel-signal-loop", daemon=True)
        panel_signal_thread.start()
        force_exit_timer: threading.Timer | None = None
        _quit_lock = threading.Lock()
        _quit_started = False

        if open_panel_on_start:
            logger.info("open_panel_on_start=True, queuing open-panel command")
            popup_manager.panel_queue.put("open-panel")
        else:
            logger.info("open_panel_on_start=False, not opening panel automatically")

        def show_status() -> str:
            try:
                latest = self.history.latest()
            except Exception:
                latest = None
            mode_str = t("tray_mode_isolated") if self.app.isolate_mode else t("tray_mode_watching")
            if latest is None:
                return t("tray_status_waiting", mode=mode_str)
            if latest.status == "ok":
                return self._limit_title(t("tray_status_latest", mode=mode_str, hash=latest.image_hash[:10]))
            return self._limit_title(t("tray_status_error", mode=mode_str, error=latest.error))

        def ocr_once(_icon, _item) -> None:
            def _on_ocr_done(event: ClipboardEvent | None) -> None:
                if event is None:
                    logger.info("Manual OCR once: no clipboard image found")
                elif event.status == "ok":
                    logger.info("Manual OCR once success: %s", event.image_hash[:10])
                else:
                    logger.warning("Manual OCR once failed: %s", event.error)
                try:
                    icon.title = show_status()
                except Exception:
                    pass

            started = self.app.run_once_async(callback=_on_ocr_done)
            if not started:
                logger.info("Manual OCR once: OCR already in progress or no image")
                try:
                    icon.title = show_status()
                except Exception:
                    pass

        def notify_success(event: ClipboardEvent) -> None:
            popup_manager.show_popup(t("tray_ocr_success_title"), event.latex)
            logger.info("OCR success popup emitted hash=%s", event.image_hash[:10])

        def refresh(_icon, _item) -> None:
            icon.title = show_status()

        def _force_exit() -> None:
            logger.warning("Forcing exit after timeout - normal shutdown did not complete")
            if sys.platform == "win32":
                try:
                    from .platform_utils import USER32
                    if USER32 is not None:
                        USER32.BlockInput(False)
                except Exception:
                    pass
            try:
                self.app.stop()
            except Exception:
                pass
            try:
                self.history.close()
            except Exception:
                pass
            try:
                release_single_instance_lock()
            except Exception:
                pass
            os._exit(0)

        def quit_app(icon, _item) -> None:
            nonlocal force_exit_timer, _quit_started
            with _quit_lock:
                if _quit_started:
                    return
                _quit_started = True
            logger.info("Tray exit requested")
            popup_manager.request_shutdown()
            try:
                threading.Thread(target=icon.stop, daemon=True).start()
            except Exception:
                pass
            if force_exit_timer is None:
                force_exit_timer = threading.Timer(8.0, _force_exit)
                force_exit_timer.daemon = True
                force_exit_timer.start()

        def open_control_panel(_icon, _item) -> None:
            popup_manager.open_panel()

        def toggle_watcher(_icon, item) -> None:
            if self.app.is_running:
                logger.info("Stopping watcher from tray menu")

                def _do_stop():
                    try:
                        self.app.stop()
                    except Exception as exc:
                        logger.exception("Error stopping watcher: %s", exc)
                    try:
                        icon.title = show_status()
                    except Exception:
                        pass

                threading.Thread(target=_do_stop, daemon=True).start()
            else:
                logger.info("Starting watcher from tray menu")
                try:
                    self.app.start()
                except Exception as exc:
                    logger.exception("Error starting watcher: %s", exc)
                try:
                    icon.title = show_status()
                except Exception:
                    pass

        def toggle_isolate_mode(_icon, item) -> None:
            new_mode = not self.app.isolate_mode
            logger.info("Toggling isolate_mode to %s from tray menu", new_mode)

            def _do_toggle():
                try:
                    was_running = self.app.is_running
                    if was_running:
                        self.app.stop()
                    self.app.restart_watcher(isolate_mode=new_mode)
                except Exception as exc:
                    logger.exception("Error toggling isolate mode: %s", exc)
                try:
                    icon.title = show_status()
                except Exception:
                    pass

            threading.Thread(target=_do_toggle, daemon=True).start()

        def toggle_startup(_icon, item) -> None:
            current = is_startup_enabled()
            new_state = not current
            logger.info("Toggling startup enabled to %s from tray menu", new_state)
            try:
                set_startup_enabled(new_state)
            except Exception as exc:
                logger.exception("Error toggling startup: %s", exc)

        def open_runtime_terminal(_icon, _item) -> None:
            log_path = private_cfg.get("log_file")
            try:
                _open_runtime_terminal(self.app.script_path, log_path)
            except Exception as exc:
                logger.exception("Error opening runtime terminal: %s", exc)

        def open_config_folder(_icon, _item) -> None:
            config_dir = get_config_dir()
            resolved_dir = config_dir.resolve()
            if ".." in config_dir.parts:
                logger.warning("Config dir contains path traversal, refusing to open: %s", config_dir)
                return
            if sys.platform == "win32":
                import subprocess
                subprocess.Popen(["explorer.exe", str(resolved_dir)])
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", str(resolved_dir)])
            else:
                import subprocess
                import os
                subprocess.Popen(["xdg-open", str(resolved_dir)])

        def show_about(_icon, _item) -> None:
            from . import __version__
            title = t("tray_about_title", version=__version__)
            mode_str = t("tray_mode_isolated") if self.app.isolate_mode else t("tray_mode_watching")
            message = t(
                "tray_about_message",
                version=__version__,
                mode=mode_str,
                script=self.app.script_path.name,
                interval=self.app.interval,
            )
            popup_manager.show_popup(title, message, timeout_ms=8000)

        def _build_script_menu_items() -> list:
            items: list = []
            for entry in self.app.registry.get_enabled_scripts():
                try:
                    tray_items = entry.script.get_tray_menu_items()
                except Exception:
                    logger.exception("Failed to get tray menu items from script %s", entry.script.name)
                    tray_items = []
                for ti in tray_items:
                    try:
                        pystray_item = _convert_tray_menu_item(ti)
                        if pystray_item is not None:
                            items.append(pystray_item)
                    except Exception:
                        logger.exception("Failed to convert tray menu item from script %s", entry.script.name)
            return items

        def _convert_tray_menu_item(ti):
            if ti.separator:
                return Menu.SEPARATOR

            label = ti.label() if callable(ti.label) else ti.label
            if not label:
                return None

            if ti.items is not None:
                sub_items = []
                for sub in ti.items:
                    converted = _convert_tray_menu_item(sub)
                    if converted is not None:
                        sub_items.append(converted)
                return MenuItem(label, Menu(*sub_items))

            if ti.action is not None:
                def _make_action(action=ti.action):
                    def _on_menu_click(_icon, _item):
                        try:
                            action()
                        except Exception:
                            logger.exception("Error in tray menu action")
                    return _on_menu_click

                kwargs = {}
                if ti.checked is not None:
                    kwargs["checked"] = ti.checked
                if ti.enabled is not True:
                    kwargs["enabled"] = ti.enabled
                return MenuItem(label, _make_action(ti.action), **kwargs)

            return MenuItem(label, lambda _icon, _item: None)

        script_menu_items = _build_script_menu_items()

        menu_items = [
            MenuItem(t("tray_control_panel"), open_control_panel),
            Menu.SEPARATOR,
            MenuItem(t("tray_start_stop_watcher"), toggle_watcher),
            MenuItem(t("tray_isolate_mode"), toggle_isolate_mode, checked=lambda item: self.app.isolate_mode),
            Menu.SEPARATOR,
            MenuItem(t("tray_ocr_once"), ocr_once),
            MenuItem(t("tray_refresh_status"), refresh),
            Menu.SEPARATOR,
            MenuItem(t("tray_open_terminal"), open_runtime_terminal),
            MenuItem(t("tray_open_config_folder"), open_config_folder),
            MenuItem(t("tray_startup_windows"), toggle_startup, checked=lambda item: is_startup_enabled()),
            Menu.SEPARATOR,
        ]
        if script_menu_items:
            menu_items.extend(script_menu_items)
            menu_items.append(Menu.SEPARATOR)
        menu_items.append(MenuItem(t("tray_about"), show_about))
        menu_items.append(MenuItem(t("tray_exit"), quit_app))

        menu = Menu(*menu_items)
        icon = pystray.Icon("PLatexClient", _build_icon_image(), self._limit_title(show_status()), menu)
        self.app.on_ocr_success = notify_success

        def _rebuild_tray_menu() -> None:
            new_menu_items = [
                MenuItem(t("tray_control_panel"), open_control_panel),
                Menu.SEPARATOR,
                MenuItem(t("tray_start_stop_watcher"), toggle_watcher),
                MenuItem(t("tray_isolate_mode"), toggle_isolate_mode, checked=lambda item: self.app.isolate_mode),
                Menu.SEPARATOR,
                MenuItem(t("tray_ocr_once"), ocr_once),
                MenuItem(t("tray_refresh_status"), refresh),
                Menu.SEPARATOR,
                MenuItem(t("tray_open_terminal"), open_runtime_terminal),
                MenuItem(t("tray_open_config_folder"), open_config_folder),
                MenuItem(t("tray_startup_windows"), toggle_startup, checked=lambda item: is_startup_enabled()),
                Menu.SEPARATOR,
            ]
            if script_menu_items:
                new_menu_items.extend(script_menu_items)
                new_menu_items.append(Menu.SEPARATOR)
            new_menu_items.append(MenuItem(t("tray_about"), show_about))
            new_menu_items.append(MenuItem(t("tray_exit"), quit_app))

            new_menu = Menu(*new_menu_items)
            icon.menu = new_menu
            icon.title = self._limit_title(show_status())

        on_language_changed(lambda lang: _rebuild_tray_menu())

        logger.info("Starting PlatexApp")
        self.app.start(script_configs=startup_script_configs or None)
        logger.info("PlatexApp started successfully")

        if not startup_script_configs:
            try:
                script_configs = self.app.registry.save_configs()
                if script_configs:
                    _ensure_scripts_in_config(script_configs)
            except Exception:
                logger.debug("Failed to save initial script configs", exc_info=True)

        def _tray_loop() -> None:
            try:
                icon.run()
            except Exception as exc:
                logger.exception("Error in tray loop thread: %s", exc)
                popup_manager.request_shutdown()

        logger.info("Starting tray thread")
        tray_thread = threading.Thread(target=_tray_loop, name="platex-pystray-loop", daemon=True)
        tray_thread.start()
        logger.info("Tray thread started, calling popup_loop()")

        try:
            popup_loop()
        except KeyboardInterrupt:
            logger.info("Tray interrupted by keyboard")
        except Exception as exc:
            logger.exception("Error in tray main loop: %s", exc)
        finally:
            popup_manager.request_shutdown()
            try:
                from PyQt6.QtWidgets import QApplication
                qt_app = QApplication.instance()
                if qt_app is not None:
                    qt_app.quit()
            except Exception:
                pass
            try:
                icon.stop()
            except Exception:
                pass
            tray_thread.join(timeout=1.0)
            if force_exit_timer is not None:
                try:
                    force_exit_timer.cancel()
                except Exception:
                    pass
            signal.signal(signal.SIGINT, previous_sigint_handler)
            if panel_event_handle is not None:
                try:
                    KERNEL32.CloseHandle(panel_event_handle)
                except Exception:
                    pass
            try:
                self.app.stop()
            except Exception:
                logger.exception("Error stopping app during tray shutdown")
            try:
                self.history.close()
            except Exception:
                pass
            try:
                release_single_instance_lock()
            except Exception:
                pass
        return 0
