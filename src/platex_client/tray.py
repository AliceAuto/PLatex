from __future__ import annotations

import json
import logging
import os
import queue
import signal
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from .app import PlatexApp
from .history import HistoryStore
from .models import ClipboardEvent


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


def _private_config_path() -> Path:
    config_dir = Path(user_config_dir("PLatexClient", "Copilot"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "private_config.json"


def _load_private_config(default_script: Path) -> dict[str, Any]:
    path = _private_config_path()
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {
        "auto_start": False,
        "active_script": str(default_script),
        "mounted_scripts": [str(default_script)],
        "private_env": {},
    }


def _save_private_config(payload: dict[str, Any]) -> None:
    _private_config_path().write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" tray'
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


def _parse_env_lines(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key:
            result[key] = value.strip()
    return result


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

        private_cfg = _load_private_config(self.app.script_path)
        mounted_scripts = [str(Path(p)) for p in private_cfg.get("mounted_scripts", []) if isinstance(p, str)]
        if str(self.app.script_path) not in mounted_scripts:
            mounted_scripts.append(str(self.app.script_path))
        active_script_raw = private_cfg.get("active_script")
        active_script = Path(active_script_raw) if isinstance(active_script_raw, str) and active_script_raw else self.app.script_path
        if active_script.exists():
            self.app.script_path = active_script

        private_env = private_cfg.get("private_env", {})
        if isinstance(private_env, dict):
            for key, value in private_env.items():
                if isinstance(key, str) and isinstance(value, str):
                    os.environ[key] = value

        popup_queue: queue.Queue[tuple[str, str, int] | None] = queue.Queue()
        panel_queue: queue.Queue[str | None] = queue.Queue()
        popup_stop = threading.Event()

        def popup_loop() -> None:
            try:
                from PyQt6.QtCore import QTimer, Qt
                from PyQt6.QtWidgets import (
                    QApplication,
                    QCheckBox,
                    QFileDialog,
                    QHBoxLayout,
                    QLabel,
                    QLineEdit,
                    QListWidget,
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
            panel_window: QWidget | None = None

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
                    self.auto_start.setChecked(_is_startup_enabled())
                    root.addWidget(self.auto_start)

                    root.addWidget(QLabel("当前挂载脚本"))
                    script_row = QHBoxLayout()
                    self.active_script = QLineEdit(str(controller.app.script_path))
                    btn_browse_active = QPushButton("浏览")
                    script_row.addWidget(self.active_script)
                    script_row.addWidget(btn_browse_active)
                    root.addLayout(script_row)

                    root.addWidget(QLabel("挂载脚本管理"))
                    self.script_list = QListWidget()
                    for item in mounted_scripts:
                        self.script_list.addItem(item)
                    root.addWidget(self.script_list)

                    list_btns = QHBoxLayout()
                    btn_add = QPushButton("添加脚本")
                    btn_remove = QPushButton("移除选中")
                    btn_use = QPushButton("设为当前")
                    list_btns.addWidget(btn_add)
                    list_btns.addWidget(btn_remove)
                    list_btns.addWidget(btn_use)
                    root.addLayout(list_btns)

                    root.addWidget(QLabel("私有配置（每行 KEY=VALUE）"))
                    self.private_env_text = QPlainTextEdit()
                    env_lines: list[str] = []
                    for k, v in private_env.items() if isinstance(private_env, dict) else []:
                        if isinstance(k, str) and isinstance(v, str):
                            env_lines.append(f"{k}={v}")
                    self.private_env_text.setPlainText("\n".join(env_lines))
                    root.addWidget(self.private_env_text)

                    action_row = QHBoxLayout()
                    btn_save = QPushButton("保存并应用")
                    btn_close = QPushButton("关闭")
                    action_row.addWidget(btn_save)
                    action_row.addWidget(btn_close)
                    root.addLayout(action_row)

                    def _browse_target(line_edit: QLineEdit) -> None:
                        path, _ = QFileDialog.getOpenFileName(self, "选择脚本", str(Path(line_edit.text() or Path.cwd()).parent), "Python (*.py)")
                        if path:
                            line_edit.setText(path)

                    def _add_script() -> None:
                        path, _ = QFileDialog.getOpenFileName(self, "添加挂载脚本", str(Path.cwd()), "Python (*.py)")
                        if not path:
                            return
                        items = [self.script_list.item(i).text() for i in range(self.script_list.count())]
                        if path not in items:
                            self.script_list.addItem(path)

                    def _remove_script() -> None:
                        row = self.script_list.currentRow()
                        if row >= 0:
                            self.script_list.takeItem(row)

                    def _use_selected() -> None:
                        item = self.script_list.currentItem()
                        if item is not None:
                            self.active_script.setText(item.text())

                    def _save_apply() -> None:
                        chosen = Path(self.active_script.text().strip())
                        if not chosen.exists():
                            QMessageBox.warning(self, "路径无效", "当前挂载脚本不存在，请重新选择。")
                            return

                        scripts = [self.script_list.item(i).text() for i in range(self.script_list.count())]
                        if str(chosen) not in scripts:
                            scripts.append(str(chosen))

                        env_map = _parse_env_lines(self.private_env_text.toPlainText())

                        try:
                            _set_startup_enabled(self.auto_start.isChecked())
                        except Exception as exc:  # noqa: BLE001
                            QMessageBox.warning(self, "开机自启失败", str(exc))
                            return

                        payload = {
                            "auto_start": bool(self.auto_start.isChecked()),
                            "active_script": str(chosen),
                            "mounted_scripts": scripts,
                            "private_env": env_map,
                        }
                        try:
                            _save_private_config(payload)
                        except Exception as exc:  # noqa: BLE001
                            QMessageBox.warning(self, "保存失败", str(exc))
                            return

                        for k, v in env_map.items():
                            os.environ[k] = v

                        try:
                            was_running = controller.app._worker is not None and controller.app._worker.is_alive()
                            controller.app.stop()
                            controller.app.script_path = chosen
                            controller.app._watcher = None
                            controller.app._stop_event.clear()
                            if was_running:
                                controller.app.start()
                        except Exception as exc:  # noqa: BLE001
                            QMessageBox.warning(self, "应用失败", str(exc))
                            return

                        logger.info("Control panel applied: script=%s auto_start=%s", chosen, self.auto_start.isChecked())
                        QMessageBox.information(self, "已保存", "配置已保存并应用。")

                    btn_browse_active.clicked.connect(lambda: _browse_target(self.active_script))
                    btn_add.clicked.connect(_add_script)
                    btn_remove.clicked.connect(_remove_script)
                    btn_use.clicked.connect(_use_selected)
                    btn_save.clicked.connect(_save_apply)
                    btn_close.clicked.connect(self.close)

            while not popup_stop.is_set():
                _handle_panel_commands()

                try:
                    item = popup_queue.get(timeout=0.1)
                except queue.Empty:
                    app.processEvents()
                    continue

                if item is None:
                    break

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
                app.processEvents()

            app.quit()

        popup_thread = threading.Thread(target=popup_loop, name="platex-qt-popup-loop", daemon=True)
        popup_thread.start()

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
            self.app.stop()
        return 0
