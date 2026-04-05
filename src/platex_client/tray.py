from __future__ import annotations

import ctypes
import logging
import os
import queue
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .app import PlatexApp
from .config import default_config_path
from .history import HistoryStore
from .models import ClipboardEvent


_INSTANCE_PANEL_EVENT_NAME = r"Local\PLatexClient_ShowControlPanel"

if sys.platform == "win32":
    _kernel32 = ctypes.windll.kernel32
    _EVENT_MODIFY_STATE = 0x0002
    _SYNCHRONIZE = 0x00100000
    _INFINITE = 0xFFFFFFFF


def _load_pystray():
    try:
        import pystray
        from pystray import Menu, MenuItem
    except ImportError as exc:  # pragma: no cover - optional dependency fallback
        raise RuntimeError("pystray is required for tray mode. Install project dependencies first.") from exc

    return pystray, Menu, MenuItem


def _build_icon_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (20, 24, 31, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, outline=(122, 162, 255, 255), width=3)
    draw.line((18, 22, 18, 42), fill=(122, 162, 255, 255), width=4)
    draw.line((46, 22, 46, 42), fill=(122, 162, 255, 255), width=4)
    draw.line((18, 42, 32, 30), fill=(122, 162, 255, 255), width=4)
    draw.line((32, 30, 46, 42), fill=(122, 162, 255, 255), width=4)
    return image


def _panel_config_path() -> Path:
    cwd = Path.cwd()
    candidates = [
        cwd / "config.yaml",
        cwd / "config.example.yaml",
        default_config_path(),
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), candidates[-1])
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_panel_config(default_script: Path) -> dict[str, Any]:
    path = _panel_config_path()
    payload: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                payload = loaded
        except Exception:
            payload = {}

    script_val = payload.get("script")
    active_script = str(default_script)
    if isinstance(script_val, str) and script_val.strip():
        active_script = script_val

    return {
        "db_path": payload.get("db_path") or "",
        "script": active_script,
        "log_file": payload.get("log_file") or "",
        "interval": float(payload.get("interval", 0.8)),
        "isolate_mode": bool(payload.get("isolate_mode", False)),
        "glm_api_key": payload.get("glm_api_key") or "",
        "glm_model": payload.get("glm_model") or "",
        "glm_base_url": payload.get("glm_base_url") or "",
        "auto_start": bool(payload.get("auto_start", False)),
        "ui_language": str(payload.get("ui_language", "en")),
        "language_pack": str(payload.get("language_pack", "")),
    }


def _save_panel_config(payload: dict[str, Any]) -> None:
    clean = {k: v for k, v in payload.items() if v not in (None, "")}
    _panel_config_path().write_text(yaml.safe_dump(clean, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" tray'
    if sys.platform == "win32":
        exe = Path(sys.executable)
        # Prefer pythonw.exe in startup to avoid showing a console window.
        if exe.name.lower() == "python.exe":
            pythonw = exe.with_name("pythonw.exe")
            if pythonw.exists():
                return f'"{pythonw}" -m platex_client.cli tray'
    return f'"{sys.executable}" -m platex_client.cli tray'


def _set_startup_enabled(enabled: bool) -> None:
    if sys.platform != "win32":
        return

    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "PLatexClient"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, _startup_command())
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass


def _is_startup_enabled() -> bool:
    if sys.platform != "win32":
        return False

    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "PLatexClient"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, app_name)
            return isinstance(value, str) and bool(value.strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _open_runtime_terminal(script_path: Path, log_path: str | None) -> None:
    if sys.platform != "win32":
        raise RuntimeError("Open terminal is currently supported on Windows only.")

    workdir = script_path.parent if script_path.exists() else Path.cwd()
    log_file = Path(log_path).expanduser() if log_path else None
    safe_workdir = str(workdir).replace("'", "''")

    ps_lines = [
        f"Set-Location -LiteralPath '{safe_workdir}'",
        "Write-Host 'PLatex runtime terminal' -ForegroundColor Cyan",
        "Write-Host 'You can run: .\\platex-client.exe logs --limit 200' -ForegroundColor DarkGray",
    ]
    if log_file is not None:
        safe_log = str(log_file).replace("'", "''")
        ps_lines.extend(
            [
                f"if (Test-Path -LiteralPath '{safe_log}') {{",
                "  Write-Host ''",
                f"  Write-Host 'Tailing log: {safe_log}' -ForegroundColor Green",
                f"  Get-Content -LiteralPath '{safe_log}' -Tail 50",
                "}",
            ]
        )

    command = "; ".join(ps_lines)
    subprocess.Popen(
        ["powershell.exe", "-NoExit", "-ExecutionPolicy", "Bypass", "-Command", command],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )


def _create_instance_panel_event():
    if sys.platform != "win32":
        return None

    handle = _kernel32.CreateEventW(None, False, False, _INSTANCE_PANEL_EVENT_NAME)
    if not handle:
        return None
    return handle


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

    def run(self) -> int:
        logger = logging.getLogger("platex.tray")
        pystray, Menu, MenuItem = _load_pystray()
        previous_sigint_handler = signal.getsignal(signal.SIGINT)

        private_cfg = _load_panel_config(self.app.script_path)
        active_script_raw = private_cfg.get("script")
        active_script = Path(active_script_raw) if isinstance(active_script_raw, str) and active_script_raw else self.app.script_path
        if active_script.exists():
            self.app.script_path = active_script

        popup_queue: queue.Queue[tuple[str, str, int] | None] = queue.Queue()
        panel_queue: queue.Queue[str | None] = queue.Queue()
        popup_stop = threading.Event()
        panel_event_handle = _create_instance_panel_event()

        def popup_loop() -> None:
            try:
                from PyQt6.QtCore import QTimer, Qt
                from PyQt6.QtWidgets import (
                    QApplication,
                    QCheckBox,
                    QComboBox,
                    QHBoxLayout,
                    QLabel,
                    QMessageBox,
                    QPlainTextEdit,
                    QPushButton,
                    QVBoxLayout,
                    QWidget,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug("PyQt popup unavailable: %s", exc)
                return

            app = QApplication([])
            app.setQuitOnLastWindowClosed(False)
            panel_window: QWidget | None = None
            active_popups: list[QWidget] = []

            def _handle_panel_commands() -> None:
                nonlocal panel_window
                while True:
                    try:
                        panel_cmd = panel_queue.get_nowait()
                    except queue.Empty:
                        break

                    if panel_cmd == "open-panel":
                        if panel_window is None or not panel_window.isVisible():
                            panel_window = _ControlPanel()
                            panel_window.show()
                        else:
                            panel_window.raise_()
                            panel_window.activateWindow()

            class _Popup(QWidget):
                def __init__(self, title: str, message: str) -> None:
                    super().__init__(None)
                    self._fade_timer: QTimer | None = None
                    self._fade_step = 0
                    self._fade_total_steps = 24
                    self.setWindowTitle(title)
                    self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
                    self.setWindowFlag(Qt.WindowType.Tool, True)
                    self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                    self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
                    self.setFixedSize(560, 180)
                    self.setStyleSheet(
                        "background:#ffffff;border:1px solid #7aa2ff;border-radius:10px;"
                        "color:#111111;"
                    )

                    layout = QVBoxLayout(self)
                    layout.setContentsMargins(16, 12, 16, 12)
                    layout.setSpacing(8)

                    title_label = QLabel(title)
                    title_label.setStyleSheet("font-size:15px;font-weight:700;color:#1f2937;")
                    body_label = QLabel(message)
                    body_label.setWordWrap(True)
                    body_label.setStyleSheet("font-size:13px;line-height:1.35;color:#111827;")

                    layout.addWidget(title_label)
                    layout.addWidget(body_label)

                def mousePressEvent(self, event):  # noqa: N802
                    self.close()
                    event.accept()

                def keyPressEvent(self, event):  # noqa: N802
                    self.close()
                    event.accept()

                def start_auto_fade(self, timeout_ms: int) -> None:
                    hold_ms = max(500, timeout_ms - 700)
                    QTimer.singleShot(hold_ms, self._begin_fade)

                def _begin_fade(self) -> None:
                    if not self.isVisible():
                        return
                    self._fade_step = 0
                    self._fade_timer = QTimer(self)
                    self._fade_timer.timeout.connect(self._fade_tick)
                    self._fade_timer.start(30)

                def _fade_tick(self) -> None:
                    if not self.isVisible():
                        if self._fade_timer is not None:
                            self._fade_timer.stop()
                        return
                    self._fade_step += 1
                    opacity = max(0.0, 1.0 - (self._fade_step / self._fade_total_steps))
                    self.setWindowOpacity(opacity)
                    if self._fade_step >= self._fade_total_steps:
                        if self._fade_timer is not None:
                            self._fade_timer.stop()
                        self.close()

            controller = self

            class _ControlPanel(QWidget):
                def __init__(self) -> None:
                    super().__init__(None)
                    self.setWindowTitle("PLatex 控制面板")
                    self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                    self.setMinimumSize(640, 520)

                    root = QVBoxLayout(self)
                    root.setContentsMargins(14, 14, 14, 14)
                    root.setSpacing(10)

                    self.auto_start = QCheckBox("开机自启")
                    root.addWidget(self.auto_start)

                    lang_row = QHBoxLayout()
                    lang_row.addWidget(QLabel("客户端语言"))
                    self.ui_language = QComboBox()
                    self.ui_language.addItem("中文（zh-cn）", "zh-cn")
                    self.ui_language.addItem("English (en)", "en")
                    lang_row.addWidget(self.ui_language)
                    root.addLayout(lang_row)

                    root.addWidget(QLabel("配置文件（完整 YAML，可滚动编辑）"))
                    self.yaml_editor = QPlainTextEdit()
                    self.yaml_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
                    self.yaml_editor.setPlainText(self._load_yaml_text())
                    root.addWidget(self.yaml_editor)

                    self._sync_ui_from_yaml()

                    action_row = QHBoxLayout()
                    btn_save = QPushButton("保存并应用")
                    btn_terminal = QPushButton("打开终端")
                    btn_close = QPushButton("关闭")
                    action_row.addWidget(btn_save)
                    action_row.addWidget(btn_terminal)
                    action_row.addWidget(btn_close)
                    root.addLayout(action_row)

                    btn_save.clicked.connect(self._save_apply)
                    btn_terminal.clicked.connect(self._open_terminal)
                    btn_close.clicked.connect(self.close)

                def _sync_ui_from_yaml(self) -> None:
                    payload: dict[str, Any] = {}
                    try:
                        payload = self._parse_yaml()
                    except Exception:
                        payload = {}

                    auto_start = bool(payload.get("auto_start", _is_startup_enabled() or bool(private_cfg.get("auto_start", False))))
                    self.auto_start.setChecked(auto_start)

                    lang = str(payload.get("ui_language", private_cfg.get("ui_language", "en"))).strip().lower() or "en"
                    lang_idx = self.ui_language.findData(lang)
                    if lang_idx < 0:
                        lang_idx = self.ui_language.findData("en")
                    self.ui_language.setCurrentIndex(max(0, lang_idx))

                def _load_yaml_text(self) -> str:
                    cfg_path = _panel_config_path()
                    if cfg_path.exists():
                        return cfg_path.read_text(encoding="utf-8")

                    seed = dict(private_cfg)
                    seed["script"] = str(controller.app.script_path)
                    seed["auto_start"] = bool(_is_startup_enabled() or seed.get("auto_start", False))
                    return yaml.safe_dump(seed, sort_keys=False, allow_unicode=True)

                def _parse_yaml(self) -> dict[str, Any]:
                    raw = self.yaml_editor.toPlainText()
                    loaded = yaml.safe_load(raw)
                    if loaded is None:
                        return {}
                    if not isinstance(loaded, dict):
                        raise ValueError("YAML 顶层必须是对象（key: value）。")
                    return loaded

                def _save_apply(self) -> None:
                    try:
                        payload = self._parse_yaml()
                    except Exception as exc:  # noqa: BLE001
                        QMessageBox.warning(self, "YAML 解析失败", str(exc))
                        return

                    script_val = payload.get("script")
                    chosen = controller.app.script_path
                    if isinstance(script_val, str) and script_val.strip():
                        chosen = Path(script_val.strip())
                    if not chosen.exists():
                        QMessageBox.warning(self, "路径无效", "YAML 中 script 指向的脚本不存在。")
                        return

                    interval_raw = payload.get("interval", controller.app.interval)
                    try:
                        interval = float(interval_raw)
                    except Exception:  # noqa: BLE001
                        QMessageBox.warning(self, "配置无效", "YAML 中 interval 必须是数字。")
                        return

                    isolate_mode = bool(payload.get("isolate_mode", controller.app.isolate_mode))
                    auto_start = bool(self.auto_start.isChecked())
                    ui_language = str(self.ui_language.currentData() or "en")

                    payload["auto_start"] = auto_start
                    payload["ui_language"] = ui_language

                    try:
                        _set_startup_enabled(auto_start)
                    except Exception as exc:  # noqa: BLE001
                        QMessageBox.warning(self, "开机自启失败", str(exc))
                        return

                    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
                    try:
                        _panel_config_path().write_text(text, encoding="utf-8")
                        self.yaml_editor.setPlainText(text)
                    except Exception as exc:  # noqa: BLE001
                        QMessageBox.warning(self, "保存失败", str(exc))
                        return

                    glm_api_key = payload.get("glm_api_key")
                    glm_model = payload.get("glm_model")
                    glm_base_url = payload.get("glm_base_url")
                    if isinstance(glm_api_key, str) and glm_api_key:
                        os.environ["GLM_API_KEY"] = glm_api_key
                    if isinstance(glm_model, str) and glm_model:
                        os.environ["GLM_MODEL"] = glm_model
                    if isinstance(glm_base_url, str) and glm_base_url:
                        os.environ["GLM_BASE_URL"] = glm_base_url

                    try:
                        was_running = controller.app._worker is not None and controller.app._worker.is_alive()
                        controller.app.stop()
                        controller.app.script_path = chosen
                        controller.app.interval = interval
                        controller.app.isolate_mode = isolate_mode
                        controller.app._watcher = None
                        controller.app._stop_event.clear()
                        if was_running:
                            controller.app.start()
                    except Exception as exc:  # noqa: BLE001
                        QMessageBox.warning(self, "应用失败", str(exc))
                        return

                    logger.info("Control panel applied: script=%s auto_start=%s", chosen, auto_start)
                    QMessageBox.information(self, "已保存", "YAML 配置已保存并应用。")

                def _open_terminal(self) -> None:
                    payload: dict[str, Any] = {}
                    try:
                        payload = self._parse_yaml()
                    except Exception:
                        payload = {}

                    script_val = payload.get("script")
                    log_val = payload.get("log_file")
                    script_path = Path(script_val.strip()) if isinstance(script_val, str) and script_val.strip() else controller.app.script_path
                    log_path = log_val.strip() if isinstance(log_val, str) else ""
                    _open_runtime_terminal(script_path, log_path)

            def _pump_messages() -> None:
                _handle_panel_commands()
                while True:
                    try:
                        item = popup_queue.get_nowait()
                    except queue.Empty:
                        break

                    if item is None:
                        app.quit()
                        return

                    title, latex, timeout_ms = item
                    preview = latex.replace("\n", " ").strip()
                    if len(preview) > 220:
                        preview = preview[:217] + "..."
                    message = f"{preview or 'OCR completed'}\n\n结果已写入剪贴板，直接粘贴即可。"

                    popup = _Popup(title, message)
                    screen = app.primaryScreen()
                    if screen is not None:
                        available = screen.availableGeometry()
                        x = max(available.left() + 8, available.right() - popup.width() - 20)
                        y = available.top() + 24
                        popup.move(x, y)

                    popup.setWindowOpacity(1.0)
                    popup.show()
                    popup.raise_()
                    popup.activateWindow()
                    popup.start_auto_fade(timeout_ms)
                    active_popups.append(popup)

                    def _release_popup_ref(_obj=None, *, _popup=popup) -> None:
                        try:
                            active_popups.remove(_popup)
                        except ValueError:
                            pass

                    popup.destroyed.connect(_release_popup_ref)

            pump_timer = QTimer()
            pump_timer.setInterval(16)
            pump_timer.timeout.connect(_pump_messages)
            pump_timer.start()

            app.exec()

        popup_thread = threading.Thread(target=popup_loop, name="platex-qt-popup-loop", daemon=True)
        popup_thread.start()

        def _panel_signal_loop() -> None:
            if panel_event_handle is None:
                return
            while not popup_stop.is_set():
                result = _kernel32.WaitForSingleObject(panel_event_handle, 250)
                if result == 0:
                    panel_queue.put("open-panel")

        panel_signal_thread = threading.Thread(target=_panel_signal_loop, name="platex-panel-signal-loop", daemon=True)
        panel_signal_thread.start()

        def show_success_popup(title: str, latex: str, timeout_ms: int = 12000) -> None:
            if popup_stop.is_set():
                return
            popup_queue.put((title, latex, timeout_ms))

        def open_control_panel(_icon, _item) -> None:
            if popup_stop.is_set():
                return
            panel_queue.put("open-panel")

        def show_status() -> str:
            latest = self.history.latest()
            mode = "isolated" if self.app.isolate_mode else "watching"
            if latest is None:
                return f"PLatex Client | {mode} | waiting for clipboard image"
            if latest.status == "ok":
                return self._limit_title(f"PLatex Client | {mode} | latest {latest.image_hash[:10]}")
            return self._limit_title(f"PLatex Client | {mode} | last error {latest.error}")

        def ocr_once(_icon, _item) -> None:
            event = self.app.run_once()
            if event is None:
                logger.info("Manual OCR once: no clipboard image found")
            elif event.status == "ok":
                logger.info("Manual OCR once success: %s", event.image_hash[:10])
            else:
                logger.warning("Manual OCR once failed: %s", event.error)
            icon.title = show_status()

        def notify_success(event: ClipboardEvent) -> None:
            show_success_popup("PLatex OCR Success", event.latex)
            logger.info("OCR success popup emitted hash=%s", event.image_hash[:10])

        def refresh(_icon, _item) -> None:
            icon.title = show_status()

        def quit_app(icon, _item) -> None:
            logger.info("Tray exit requested")
            self.app.stop()
            icon.stop()

        menu = Menu(
            MenuItem("Control Panel", open_control_panel),
            MenuItem("OCR once now", ocr_once),
            MenuItem("Refresh status", refresh),
            MenuItem("Exit", quit_app),
        )
        icon = pystray.Icon("PLatexClient", _build_icon_image(), self._limit_title(show_status()), menu)
        self.app.on_ocr_success = notify_success
        self.app.start()
        try:
            # In console-launched tray mode, ignore Ctrl+C and exit from tray menu.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            icon.run()
        except KeyboardInterrupt:
            logger.info("Tray interrupted by keyboard")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error in tray main loop: %s", exc)
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)
            popup_stop.set()
            popup_queue.put(None)
            panel_queue.put(None)
            popup_thread.join(timeout=1.0)
            if panel_event_handle is not None:
                try:
                    _kernel32.CloseHandle(panel_event_handle)
                except Exception:
                    pass
            self.app.stop()
        return 0
