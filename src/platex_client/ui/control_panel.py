from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("platex.ui.control_panel")

from ..config import ConfigStore
from ..config_manager import ConfigManager
from ..i18n import t, on_language_changed
from ..platform_utils import is_startup_enabled, set_startup_enabled
from ..secrets import set_secret
from .general_tab import GeneralTab
from .glass_utils import GLASS_STYLESHEET, enable_acrylic_for_window
from .log_tab import LogTab


class ControlPanel(QWidget):
    def __init__(self, controller_ref: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller_ref
        self._dwm_applied = False
        self.setObjectName("GlassRoot")
        self.setWindowTitle(t("window_title"))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setMinimumSize(800, 600)
        self.setStyleSheet(GLASS_STYLESHEET)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        self._tab_widget = QTabWidget()
        root.addWidget(self._tab_widget)

        self._general_tab = GeneralTab(controller_ref, self._tab_widget)
        self._tab_widget.addTab(self._general_tab, t("tab_general"))

        self._script_tabs: dict[str, QWidget] = {}
        self._script_tab_containers: dict[str, QWidget] = {}
        self._create_script_tabs()

        self._log_tab = LogTab()
        self._log_tab.bind_controller(controller_ref)
        self._tab_widget.addTab(self._log_tab, t("tab_log"))

        action_row = QHBoxLayout()
        btn_save = QPushButton(t("btn_save"))
        btn_terminal = QPushButton(t("btn_terminal"))
        btn_close = QPushButton(t("btn_close"))
        action_row.addWidget(btn_save)
        action_row.addWidget(btn_terminal)
        action_row.addWidget(btn_close)
        root.addLayout(action_row)

        self._btn_save = btn_save
        self._btn_terminal = btn_terminal
        self._btn_close = btn_close

        btn_save.clicked.connect(lambda: self._save_apply(show_result_message=True, restart_app=True))
        btn_terminal.clicked.connect(self._open_terminal)
        btn_close.clicked.connect(self.close)

        on_language_changed(self._on_language_changed)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._dwm_applied:
            self._dwm_applied = True
            hwnd = int(self.winId())
            if hwnd:
                enable_acrylic_for_window(hwnd, tint_color=0xE01E1E2E)

    def _on_language_changed(self, language: str) -> None:
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.setWindowTitle(t("window_title"))
        self._tab_widget.setTabText(self._tab_widget.indexOf(self._general_tab), t("tab_general"))
        self._tab_widget.setTabText(self._tab_widget.indexOf(self._log_tab), t("tab_log"))
        self._btn_save.setText(t("btn_save"))
        self._btn_terminal.setText(t("btn_terminal"))
        self._btn_close.setText(t("btn_close"))
        self._general_tab.retranslate_ui()
        self._log_tab.retranslate_ui()

    def closeEvent(self, event) -> None:
        if self._save_apply(show_result_message=False, restart_app=False):
            event.accept()
        else:
            event.ignore()

    def show_script_tab(self, script_name: str) -> None:
        container = self._script_tab_containers.get(script_name)
        if container is not None:
            idx = self._tab_widget.indexOf(container)
            if idx >= 0:
                self._tab_widget.setCurrentIndex(idx)

    def _create_script_tabs(self) -> None:
        registry = self._controller.app.registry
        for entry in registry.get_all_scripts():
            script = entry.script
            try:
                widget = script.create_settings_widget(self._tab_widget)
            except Exception:
                logger.exception("Failed to create settings widget for script %s", script.name)
                widget = None

            if widget is not None:
                change_cb = getattr(widget, "set_settings_changed_callback", None)
                if callable(change_cb):
                    change_cb(self._persist_script_settings)

                save_fn = getattr(widget, "save_settings", None)
                if callable(save_fn):
                    self._script_tabs[script.name] = widget

                load_fn = getattr(widget, "load_settings", None)
                if callable(load_fn):
                    try:
                        load_fn()
                    except Exception:
                        logger.exception("Failed to initialize script settings widget for %s", script.name)

                container = QWidget()
                container_layout = QVBoxLayout(container)
                container_layout.setContentsMargins(0, 0, 0, 0)
                container_layout.setSpacing(0)
                container_layout.addWidget(widget, 1)

                io_row = QHBoxLayout()
                io_row.setContentsMargins(12, 4, 12, 8)
                btn_import = QPushButton(t("btn_import_config"))
                btn_export = QPushButton(t("btn_export_config"))

                def _make_import(s=script, w=widget):
                    def _do_import():
                        try:
                            from PyQt6.QtWidgets import QFileDialog, QMessageBox

                            filepath, _ = QFileDialog.getOpenFileName(
                                self, t("dialog_import_script", name=s.display_name), str(Path.cwd()),
                                t("dialog_yaml_filter"),
                            )
                            if not filepath:
                                return
                            s.import_config(Path(filepath))
                            load_fn = getattr(w, "load_settings", None)
                            if callable(load_fn):
                                load_fn()
                            QMessageBox.information(self, t("msg_script_import_success"), t("msg_script_import_success_text", name=s.display_name))
                        except Exception as exc:
                            from PyQt6.QtWidgets import QMessageBox

                            QMessageBox.warning(self, t("msg_script_import_failed"), str(exc))
                    return _do_import

                def _make_export(s=script):
                    def _do_export():
                        try:
                            from PyQt6.QtWidgets import QFileDialog, QMessageBox

                            filepath, _ = QFileDialog.getSaveFileName(
                                self, t("dialog_export_script", name=s.display_name),
                                str(Path.cwd() / f"{s.name}-config.yaml"),
                                t("dialog_yaml_filter"),
                            )
                            if not filepath:
                                return
                            s.export_config(Path(filepath))
                            QMessageBox.information(self, t("msg_script_export_success"), t("msg_script_export_success_text", path=filepath))
                        except Exception as exc:
                            from PyQt6.QtWidgets import QMessageBox

                            QMessageBox.warning(self, t("msg_script_export_failed"), str(exc))
                    return _do_export

                btn_import.clicked.connect(_make_import())
                btn_export.clicked.connect(_make_export())
                io_row.addWidget(btn_import)
                io_row.addWidget(btn_export)
                io_row.addStretch()
                container_layout.addLayout(io_row)

                self._tab_widget.addTab(container, script.display_name)
                self._script_tab_containers[script.name] = container

    def _persist_script_settings(self) -> None:
        store = ConfigStore.instance()
        try:
            payload = self._general_tab.parse_yaml()
        except Exception:
            payload = store.build_full_payload()
        script_configs = self._controller.app.registry.save_configs()
        payload["scripts"] = script_configs

        store.request_update_and_save(payload)

        text = store.build_disk_yaml_text()
        self._general_tab.update_yaml_display_if_unfocused(text)

        self._controller.app.apply_registry_hotkeys()

    def _open_terminal(self) -> None:
        from ..tray import _open_runtime_terminal

        payload: dict[str, Any] = {}
        try:
            payload = self._general_tab.parse_yaml()
        except Exception:
            payload = {}

        script_val = payload.get("script")
        log_val = payload.get("log_file")
        script_path = Path(script_val.strip()) if isinstance(script_val, str) and script_val.strip() else self._controller.app.script_path
        log_path = log_val.strip() if isinstance(log_val, str) else ""
        _open_runtime_terminal(script_path, log_path)

    def _save_apply(self, *, show_result_message: bool = True, restart_app: bool = True) -> bool:
        import os

        try:
            payload = self._general_tab.parse_yaml()
        except Exception as exc:
            QMessageBox.warning(self, t("yaml_parse_failed"), str(exc))
            return False

        for widget in self._script_tabs.values():
            save_fn = getattr(widget, "save_settings", None)
            if callable(save_fn):
                try:
                    save_fn()
                except Exception:
                    logger.exception("Failed to flush script settings from UI")

        script_val = payload.get("script")
        chosen = self._controller.app.script_path
        if isinstance(script_val, str) and script_val.strip():
            chosen = Path(script_val.strip())
        if not chosen.exists():
            QMessageBox.warning(self, t("msg_invalid_path"), t("msg_invalid_path_text"))
            return False

        interval_raw = payload.get("interval", self._controller.app.interval)
        try:
            interval = float(interval_raw)
        except Exception:
            QMessageBox.warning(self, t("msg_invalid_config"), t("msg_invalid_interval"))
            return False

        isolate_mode = bool(payload.get("isolate_mode", self._controller.app.isolate_mode))
        auto_start = bool(self._general_tab.auto_start.isChecked())
        ui_language = str(self._general_tab.ui_language.currentData() or "en")

        payload["auto_start"] = auto_start
        payload["ui_language"] = ui_language

        script_configs: dict[str, dict[str, Any]] = {}
        if restart_app:
            edited_scripts = payload.get("scripts")
            if not isinstance(edited_scripts, dict):
                edited_scripts = {}

            baseline_scripts: dict[str, Any] = {}
            try:
                baseline_loaded = yaml.safe_load(self._general_tab.get_yaml_text())
                if isinstance(baseline_loaded, dict) and isinstance(baseline_loaded.get("scripts"), dict):
                    baseline_scripts = baseline_loaded["scripts"]
            except Exception:
                baseline_scripts = {}

            yaml_scripts_changed = edited_scripts != baseline_scripts
            if yaml_scripts_changed:
                self._controller.app.registry.load_configs(edited_scripts)
                for widget in self._script_tabs.values():
                    load_fn = getattr(widget, "load_settings", None)
                    if callable(load_fn):
                        try:
                            load_fn()
                        except Exception:
                            logger.exception("Failed to refresh script settings widget from YAML")
                script_configs = self._controller.app.registry.save_configs()
            else:
                script_configs = self._controller.app.registry.save_configs()
        else:
            script_configs = self._controller.app.registry.save_configs()

        if script_configs:
            payload["scripts"] = script_configs

        registry = self._controller.app.registry
        ocr_entries = registry.get_ocr_scripts()
        for entry in ocr_entries:
            ocr_config = entry.script.save_config()
            payload["glm_api_key"] = ocr_config.get("api_key", "")
            payload["glm_model"] = ocr_config.get("model", "")
            payload["glm_base_url"] = ocr_config.get("base_url", "")

        try:
            set_startup_enabled(auto_start)
        except Exception as exc:
            QMessageBox.warning(self, t("msg_auto_start_failed"), str(exc))
            return False

        glm_api_key = payload.get("glm_api_key")
        glm_model = payload.get("glm_model")
        glm_base_url = payload.get("glm_base_url")
        if isinstance(glm_api_key, str) and glm_api_key:
            set_secret("GLM_API_KEY", glm_api_key)
        if isinstance(glm_model, str) and glm_model:
            set_secret("GLM_MODEL", glm_model)
        if isinstance(glm_base_url, str) and glm_base_url:
            set_secret("GLM_BASE_URL", glm_base_url)

        store = ConfigStore.instance()
        try:
            store.request_update_and_save(payload)
        except Exception as exc:
            QMessageBox.warning(self, t("msg_save_failed"), str(exc))
            return False

        text = store.build_disk_yaml_text()
        self._general_tab.update_yaml_display(text)

        for widget in self._script_tabs.values():
            load_fn = getattr(widget, "load_settings", None)
            if callable(load_fn):
                try:
                    load_fn()
                except Exception:
                    logger.exception("Failed to refresh script settings widget after save")

        self._controller.app.apply_registry_hotkeys()

        if restart_app:
            try:
                self._controller.app.restart_watcher(
                    script_path=chosen,
                    interval=interval,
                    isolate_mode=isolate_mode,
                )
            except Exception as exc:
                QMessageBox.warning(self, t("msg_apply_failed"), str(exc))
                return False
        else:
            self._controller.app.script_path = chosen
            self._controller.app.interval = interval
            self._controller.app.isolate_mode = isolate_mode

        logger.info("Control panel applied: script=%s auto_start=%s", chosen, auto_start)
        self._general_tab._refresh_hotkey_status()
        if show_result_message:
            QMessageBox.information(self, t("msg_saved"), t("msg_saved_text"))
        return True
