from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import ConfigStore, _hide_api_key
from ..config_manager import ConfigManager, get_config_dir, set_config_dir
from ..i18n import t, on_language_changed, available_languages, switch_language
from ..platform_utils import is_startup_enabled, set_startup_enabled
from .glass_utils import HOTKEY_STATUS_STYLESHEET


logger = logging.getLogger("platex.ui.general_tab")


class GeneralTab(QWidget):
    def __init__(self, controller_ref: object, tab_widget: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller_ref
        self._tab_widget = tab_widget
        self._script_tabs: dict[str, QWidget] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.auto_start = QCheckBox(t("label_auto_start"))
        layout.addWidget(self.auto_start)

        lang_row = QHBoxLayout()
        lang_row.addWidget(QLabel(t("label_language")))
        self.ui_language = QComboBox()
        for lang_code, lang_name in available_languages():
            self.ui_language.addItem(lang_name, lang_code)
        lang_row.addWidget(self.ui_language)
        self.ui_language.currentIndexChanged.connect(self._on_language_selection_changed)
        layout.addLayout(lang_row)

        config_dir_row = QHBoxLayout()
        self._config_dir_label = QLabel(f"{t('label_config_dir')}:")
        config_dir_row.addWidget(self._config_dir_label)
        self._config_dir_edit = QLineEdit(str(get_config_dir()))
        self._config_dir_edit.setReadOnly(True)
        config_dir_row.addWidget(self._config_dir_edit, 1)
        self.btn_change_dir = QPushButton(t("btn_change"))
        self.btn_change_dir.clicked.connect(self._change_config_dir)
        config_dir_row.addWidget(self.btn_change_dir)
        layout.addLayout(config_dir_row)

        hotkey_status_box = self._build_hotkey_status_section()
        layout.addWidget(hotkey_status_box)

        io_row = QHBoxLayout()
        self.btn_export_all = QPushButton(t("btn_export_all"))
        self.btn_import_all = QPushButton(t("btn_import_all"))
        self.btn_export_all.clicked.connect(self._export_all_config)
        self.btn_import_all.clicked.connect(self._import_all_config)
        io_row.addWidget(self.btn_export_all)
        io_row.addWidget(self.btn_import_all)
        io_row.addStretch()
        layout.addLayout(io_row)

        self._yaml_toggle_btn = QPushButton(t("btn_show_yaml"))
        self._yaml_toggle_btn.setObjectName("YamlToggleBtn")
        self._yaml_toggle_btn.setCheckable(True)
        layout.addWidget(self._yaml_toggle_btn)

        self._yaml_container = QWidget()
        from PyQt6.QtWidgets import QPlainTextEdit

        yaml_container_layout = QVBoxLayout(self._yaml_container)
        yaml_container_layout.setContentsMargins(0, 0, 0, 0)
        self.yaml_editor = QPlainTextEdit()
        self.yaml_editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._yaml_text = self._load_yaml_text()
        self.yaml_editor.setPlainText(_hide_api_key(self._yaml_text))
        yaml_container_layout.addWidget(self.yaml_editor)
        self._yaml_container.setVisible(False)
        layout.addWidget(self._yaml_container)

        self._yaml_toggle_btn.toggled.connect(self._toggle_yaml_editor)

        self._sync_ui_from_yaml()
        self._refresh_hotkey_status()

        on_language_changed(self._on_language_changed)

    def _on_language_changed(self, language: str) -> None:
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self.auto_start.setText(t("label_auto_start"))

        current_lang = self.ui_language.currentData() or "en"
        self.ui_language.blockSignals(True)
        self.ui_language.clear()
        for lang_code, lang_name in available_languages():
            self.ui_language.addItem(lang_name, lang_code)
        idx = self.ui_language.findData(current_lang)
        if idx < 0:
            idx = self.ui_language.findData("en")
        self.ui_language.setCurrentIndex(max(0, idx))
        self.ui_language.blockSignals(False)

        self._config_dir_label.setText(f"{t('label_config_dir')}:")
        self.btn_change_dir.setText(t("btn_change"))
        self.btn_export_all.setText(t("btn_export_all"))
        self.btn_import_all.setText(t("btn_import_all"))
        self._yaml_toggle_btn.setText(t("btn_show_yaml") if not self._yaml_container.isVisible() else t("btn_hide_yaml"))
        self._hotkey_title.setText(t("label_hotkey_status"))
        self._btn_refresh.setText(t("btn_refresh"))
        self._refresh_hotkey_status()

    def _on_language_selection_changed(self, index: int) -> None:
        lang_code = self.ui_language.itemData(index)
        if lang_code and isinstance(lang_code, str):
            switch_language(lang_code)

    def _build_hotkey_status_section(self) -> QWidget:
        from PyQt6.QtWidgets import QVBoxLayout

        box = QWidget()
        box.setObjectName("HotkeyStatusBox")
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(10, 10, 10, 10)
        box_layout.setSpacing(6)
        box.setStyleSheet(HOTKEY_STATUS_STYLESHEET)

        header = QHBoxLayout()
        self._hotkey_title = QLabel(t("label_hotkey_status"))
        self._hotkey_title.setObjectName("HotkeyStatusTitle")
        header.addWidget(self._hotkey_title)
        self._btn_refresh = QPushButton(t("btn_refresh"))
        self._btn_refresh.setFixedWidth(60)
        self._btn_refresh.clicked.connect(self._refresh_hotkey_status)
        header.addWidget(self._btn_refresh)
        header.addStretch()
        box_layout.addLayout(header)

        self._hotkey_status_label = QLabel(t("msg_loading"))
        self._hotkey_status_label.setObjectName("HotkeyStatusLabel")
        self._hotkey_status_label.setWordWrap(True)
        box_layout.addWidget(self._hotkey_status_label)

        return box

    def _refresh_hotkey_status(self) -> None:
        try:
            status = self._controller.app.hotkey_listener.get_status()
        except Exception as exc:
            self._hotkey_status_label.setText(t("msg_hotkey_cannot_get", error=exc))
            return

        backend = status.get("backend", "none")
        registered = status.get("bindings", [])
        failed = status.get("failed", {})
        running = status.get("running", False)

        lines: list[str] = []
        backend_names = {"win32": t("backend_win32"), "pynput": t("backend_pynput"), "none": t("backend_none")}
        backend_str = backend_names.get(backend, backend)
        lines.append(t("msg_backend", backend=backend_str))

        if running:
            lines.append(t("msg_running", count=len(registered)))
        else:
            lines.append(t("msg_stopped"))

        if registered:
            lines.append(t("msg_registered", bindings=', '.join(registered)))
            lines.append(t("msg_all_hotkeys_ok"))
        else:
            lines.append(t("msg_no_hotkeys"))

        if failed:
            failed_items = [f"{hk} (retry {count}x)" for hk, count in failed.items()]
            lines.append(t("msg_register_failed", items=', '.join(failed_items)))
            lines.append(t("msg_resolve_tip"))
        else:
            lines.append(t("msg_no_conflict"))

        self._hotkey_status_label.setText("<br>".join(lines))

    def _change_config_dir(self) -> None:
        current = get_config_dir()
        new_dir = QFileDialog.getExistingDirectory(self, t("dialog_select_config_dir"), str(current))
        if not new_dir:
            return
        new_path = Path(new_dir)
        try:
            set_config_dir(new_path)
            self._config_dir_edit.setText(str(new_path))
            QMessageBox.information(
                self, t("msg_config_dir_changed"),
                t("msg_config_dir_changed_text", path=new_path),
            )
        except Exception as exc:
            QMessageBox.warning(self, t("msg_change_failed"), str(exc))

    def _export_all_config(self) -> None:
        filepath, _ = QFileDialog.getSaveFileName(
                self, t("dialog_export_config"), str(Path.cwd() / "platex-config.yaml"),
                t("dialog_yaml_filter"),
            )
        if not filepath:
            return
        try:
            mgr = ConfigManager(self._controller.app.registry)
            mgr.export_all(Path(filepath))
            QMessageBox.information(self, t("msg_export_success"), t("msg_export_success_text", path=filepath))
        except Exception as exc:
            QMessageBox.warning(self, t("msg_export_failed"), str(exc))

    def _import_all_config(self) -> None:
        filepath, _ = QFileDialog.getOpenFileName(
            self, t("dialog_import_config"), str(Path.cwd()),
            t("dialog_yaml_filter"),
        )
        if not filepath:
            return
        try:
            mgr = ConfigManager(self._controller.app.registry)
            result = mgr.import_all(Path(filepath))
        except Exception as exc:
            QMessageBox.warning(self, t("msg_import_failed"), str(exc))
            return

        general = result.get("general", {})
        scripts = result.get("scripts", {})

        if general:
            yaml_text = yaml.safe_dump(general, sort_keys=False, allow_unicode=True)
            self.yaml_editor.setPlainText(yaml_text)
            self._sync_ui_from_yaml()

        if scripts and self._controller.app.registry:
            self._controller.app.registry.load_configs(scripts)

        QMessageBox.information(self, t("msg_import_success"), t("msg_import_success_text"))

    def _toggle_yaml_editor(self, checked: bool) -> None:
        if checked:
            self._yaml_toggle_btn.setText(t("btn_hide_yaml"))
            self._yaml_container.setVisible(True)
        else:
            self._yaml_toggle_btn.setText(t("btn_show_yaml"))
            self._yaml_container.setVisible(False)

    def _sync_ui_from_yaml(self) -> None:
        store = ConfigStore.instance()
        payload: dict[str, Any] = {}
        try:
            payload = self._parse_yaml()
        except Exception:
            payload = {}

        auto_start = bool(payload.get("auto_start", is_startup_enabled() or store.config.auto_start))
        self.auto_start.setChecked(auto_start)

        lang = str(payload.get("ui_language", store.config.ui_language)).strip().lower() or "en"
        lang_idx = self.ui_language.findData(lang)
        if lang_idx < 0:
            lang_idx = self.ui_language.findData("en")
        self.ui_language.setCurrentIndex(max(0, lang_idx))

    def _load_yaml_text(self) -> str:
        from ..config_manager import config_file_path

        store = ConfigStore.instance()
        cfg_path = config_file_path()
        if cfg_path.exists():
            text = cfg_path.read_text(encoding="utf-8")
            self._yaml_text = text
            return text

        seed = store.build_full_payload()
        seed["script"] = str(self._controller.app.script_path)
        seed["auto_start"] = bool(is_startup_enabled() or seed.get("auto_start", False))
        script_configs = self._controller.app.registry.save_configs()
        if script_configs:
            seed["scripts"] = script_configs
        self._yaml_text = yaml.safe_dump(seed, sort_keys=False, allow_unicode=True)
        return self._yaml_text

    def _parse_yaml(self) -> dict[str, Any]:
        from ..config import _restore_api_key, _fill_masked_api_keys

        raw = self.yaml_editor.toPlainText()
        restored = _restore_api_key(raw, self._yaml_text)
        loaded = yaml.safe_load(restored)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError(t("yaml_parse_error"))
        loaded = _fill_masked_api_keys(loaded)
        return loaded

    def parse_yaml(self) -> dict[str, Any]:
        return self._parse_yaml()

    def get_yaml_text(self) -> str:
        return self._yaml_text

    def update_yaml_display(self, text: str) -> None:
        self._yaml_text = text
        self.yaml_editor.blockSignals(True)
        try:
            self.yaml_editor.setPlainText(_hide_api_key(text))
        finally:
            self.yaml_editor.blockSignals(False)

    def update_yaml_display_if_unfocused(self, text: str) -> None:
        if not self.yaml_editor.hasFocus():
            self.update_yaml_display(text)

    def is_yaml_editor_focused(self) -> bool:
        return self.yaml_editor.hasFocus()
