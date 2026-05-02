from __future__ import annotations

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import t, on_language_changed, remove_language_callback

logger = logging.getLogger("platex.ui.plugins_tab")


class PluginListItem(QWidget):
    def __init__(self, name: str, description: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PluginListItem")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self._name_label = QLabel(name)
        self._name_label.setObjectName("PluginItemName")
        layout.addWidget(self._name_label)

        self._desc_label = QLabel(description)
        self._desc_label.setObjectName("PluginItemDesc")
        self._desc_label.setWordWrap(True)
        layout.addWidget(self._desc_label)


class PluginsTab(QWidget):
    script_settings_changed = pyqtSignal()

    def __init__(self, controller_ref: object, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller_ref
        self._script_widgets: dict[str, QWidget] = {}
        self._script_names: list[str] = []
        self._current_script_name: str | None = None

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setObjectName("PluginSplitter")
        splitter.setHandleWidth(1)

        list_panel = QWidget()
        list_panel.setObjectName("PluginListPanel")
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        self._list_header = QLabel(t("tab_plugins"))
        self._list_header.setObjectName("PluginListHeader")
        self._list_header.setAlignment(Qt.AlignmentFlag.AlignCenter)
        list_layout.addWidget(self._list_header)

        self._plugin_list = QListWidget()
        self._plugin_list.setObjectName("PluginList")
        self._plugin_list.currentRowChanged.connect(self._on_plugin_selected)
        list_layout.addWidget(self._plugin_list)

        detail_panel = QWidget()
        detail_panel.setObjectName("PluginDetailPanel")
        detail_layout = QVBoxLayout(detail_panel)
        detail_layout.setContentsMargins(16, 12, 16, 12)
        detail_layout.setSpacing(8)

        self._plugin_name_label = QLabel("")
        self._plugin_name_label.setObjectName("PluginDetailName")
        detail_layout.addWidget(self._plugin_name_label)

        self._plugin_desc_label = QLabel("")
        self._plugin_desc_label.setObjectName("PluginDetailDesc")
        self._plugin_desc_label.setWordWrap(True)
        detail_layout.addWidget(self._plugin_desc_label)

        separator = QWidget()
        separator.setObjectName("PluginDetailSeparator")
        separator.setFixedHeight(1)
        detail_layout.addWidget(separator)

        self._settings_stack = QStackedWidget()
        detail_layout.addWidget(self._settings_stack, 1)

        self._empty_widget = QWidget()
        empty_layout = QVBoxLayout(self._empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label = QLabel(t("plugin_no_selection"))
        empty_label.setObjectName("PluginEmptyState")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_label)
        self._settings_stack.addWidget(self._empty_widget)

        self._no_settings_widget = QWidget()
        no_settings_layout = QVBoxLayout(self._no_settings_widget)
        no_settings_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_settings_label = QLabel(t("plugin_no_settings"))
        no_settings_label.setObjectName("PluginEmptyState")
        no_settings_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_settings_layout.addWidget(no_settings_label)
        self._settings_stack.addWidget(self._no_settings_widget)

        io_row = QHBoxLayout()
        io_row.setSpacing(8)
        self._btn_import = QPushButton(t("btn_import_config"))
        self._btn_export = QPushButton(t("btn_export_config"))
        io_row.addWidget(self._btn_import)
        io_row.addWidget(self._btn_export)
        io_row.addStretch()
        detail_layout.addLayout(io_row)

        splitter.addWidget(list_panel)
        splitter.addWidget(detail_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([200, 500])

        root_layout.addWidget(splitter)

        self._btn_import.clicked.connect(self._do_import)
        self._btn_export.clicked.connect(self._do_export)

        on_language_changed(self._on_language_changed)

    def populate(self) -> None:
        self._plugin_list.clear()
        self._script_widgets.clear()
        self._script_names.clear()

        while self._settings_stack.count() > 2:
            w = self._settings_stack.widget(2)
            if w is not None:
                self._settings_stack.removeWidget(w)
                w.deleteLater()

        registry = self._controller.app.registry
        for entry in registry.get_all_scripts():
            script = entry.script
            try:
                widget = script.create_settings_widget(self._settings_stack)
            except Exception:
                logger.exception("Failed to create settings widget for script %s", script.name)
                widget = None

            if widget is not None:
                change_cb = getattr(widget, "set_settings_changed_callback", None)
                if callable(change_cb):
                    change_cb(self._on_script_settings_changed)

                save_fn = getattr(widget, "save_settings", None)
                if callable(save_fn):
                    self._script_widgets[script.name] = widget

                load_fn = getattr(widget, "load_settings", None)
                if callable(load_fn):
                    try:
                        load_fn()
                    except Exception:
                        logger.exception("Failed to initialize script settings widget for %s", script.name)

                self._settings_stack.addWidget(widget)

            item_widget = PluginListItem(script.display_name, script.description)
            list_item = QListWidgetItem(self._plugin_list)
            list_item.setSizeHint(item_widget.sizeHint())
            list_item.setData(Qt.ItemDataRole.UserRole, script.name)
            self._plugin_list.setItemWidget(list_item, item_widget)
            self._script_names.append(script.name)

        if self._plugin_list.count() > 0:
            self._plugin_list.setCurrentRow(0)

    def get_script_widgets(self) -> dict[str, QWidget]:
        return dict(self._script_widgets)

    def show_script(self, script_name: str) -> None:
        for i, name in enumerate(self._script_names):
            if name == script_name:
                self._plugin_list.setCurrentRow(i)
                return

    def _on_plugin_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._script_names):
            self._current_script_name = None
            self._settings_stack.setCurrentIndex(0)
            self._plugin_name_label.setText("")
            self._plugin_desc_label.setText("")
            self._btn_import.setEnabled(False)
            self._btn_export.setEnabled(False)
            return

        script_name = self._script_names[row]
        self._current_script_name = script_name

        registry = self._controller.app.registry
        entry = registry.get(script_name)
        if entry is None:
            self._settings_stack.setCurrentIndex(0)
            return

        script = entry.script
        self._plugin_name_label.setText(script.display_name)
        self._plugin_desc_label.setText(script.description)

        widget = self._script_widgets.get(script_name)
        if widget is not None:
            idx = self._settings_stack.indexOf(widget)
            if idx >= 0:
                self._settings_stack.setCurrentIndex(idx)
            else:
                self._settings_stack.setCurrentIndex(1)
        else:
            self._settings_stack.setCurrentIndex(1)

        has_widget = widget is not None
        self._btn_import.setEnabled(has_widget)
        self._btn_export.setEnabled(has_widget)

    def _on_script_settings_changed(self) -> None:
        self.script_settings_changed.emit()

    def _do_import(self) -> None:
        if self._current_script_name is None:
            return
        registry = self._controller.app.registry
        entry = registry.get(self._current_script_name)
        if entry is None:
            return
        script = entry.script
        widget = self._script_widgets.get(self._current_script_name)
        if widget is None:
            return

        try:
            from PyQt6.QtWidgets import QFileDialog

            filepath, _ = QFileDialog.getOpenFileName(
                self, t("dialog_import_script", name=script.display_name), str(Path.cwd()),
                t("dialog_yaml_filter"),
            )
            if not filepath:
                return
            script.import_config(Path(filepath))
            load_fn = getattr(widget, "load_settings", None)
            if callable(load_fn):
                load_fn()
            QMessageBox.information(self, t("msg_script_import_success"), t("msg_script_import_success_text", name=script.display_name))
        except Exception as exc:
            QMessageBox.warning(self, t("msg_script_import_failed"), str(exc))

    def _do_export(self) -> None:
        if self._current_script_name is None:
            return
        registry = self._controller.app.registry
        entry = registry.get(self._current_script_name)
        if entry is None:
            return
        script = entry.script

        try:
            from PyQt6.QtWidgets import QFileDialog

            filepath, _ = QFileDialog.getSaveFileName(
                self, t("dialog_export_script", name=script.display_name),
                str(Path.cwd() / f"{script.name}-config.yaml"),
                t("dialog_yaml_filter"),
            )
            if not filepath:
                return
            script.export_config(Path(filepath))
            QMessageBox.information(self, t("msg_script_export_success"), t("msg_script_export_success_text", path=filepath))
        except Exception as exc:
            QMessageBox.warning(self, t("msg_script_export_failed"), str(exc))

    def _on_language_changed(self, language: str) -> None:
        self.retranslate_ui()

    def retranslate_ui(self) -> None:
        self._list_header.setText(t("tab_plugins"))

        for i in range(self._plugin_list.count()):
            item = self._plugin_list.item(i)
            if item is None:
                continue
            script_name = item.data(Qt.ItemDataRole.UserRole)
            if script_name is None:
                continue
            registry = self._controller.app.registry
            entry = registry.get(script_name)
            if entry is None:
                continue
            script = entry.script
            item_widget = self._plugin_list.itemWidget(item)
            if isinstance(item_widget, PluginListItem):
                item_widget._name_label.setText(script.display_name)
                item_widget._desc_label.setText(script.description)
                item_widget.adjustSize()
                item.setSizeHint(item_widget.sizeHint())

        if self._current_script_name:
            registry = self._controller.app.registry
            entry = registry.get(self._current_script_name)
            if entry is not None:
                self._plugin_name_label.setText(entry.script.display_name)
                self._plugin_desc_label.setText(entry.script.description)

        self._btn_import.setText(t("btn_import_config"))
        self._btn_export.setText(t("btn_export_config"))

        empty_labels = self._empty_widget.findChildren(QLabel)
        for lbl in empty_labels:
            lbl.setText(t("plugin_no_selection"))
        no_settings_labels = self._no_settings_widget.findChildren(QLabel)
        for lbl in no_settings_labels:
            lbl.setText(t("plugin_no_settings"))

    def cleanup(self) -> None:
        remove_language_callback(self._on_language_changed)
