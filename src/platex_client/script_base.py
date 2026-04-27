from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget
    from collections.abc import Callable


@dataclass
class TrayMenuItem:
    label: str | Callable[[], str] = ""
    action: Callable[[], None] | None = None
    items: list[TrayMenuItem] | None = None
    checked: None | bool | Callable[[], bool] = None
    enabled: bool | Callable[[], bool] = True
    separator: bool = False


class ScriptBase(ABC):
    """Base class for all PLatex scripts."""

    def __init__(self) -> None:
        self._context: Any | None = None
        self._hotkeys_changed_callback: Callable[[], None] | None = None
        self._tray_action_callback: Any | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this script."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in the UI."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of what this script does."""

    @property
    def context(self) -> Any | None:
        return self._context

    def on_context_ready(self, context: Any) -> None:
        self._context = context

    def create_settings_widget(self, parent: QWidget | None = None) -> QWidget | None:
        return None

    def get_hotkey_bindings(self) -> dict[str, str]:
        return {}

    def on_hotkey(self, action: str) -> None:
        pass

    def set_hotkeys_changed_callback(self, callback: Callable[[], None] | None) -> None:
        self._hotkeys_changed_callback = callback

    def _notify_hotkeys_changed(self) -> None:
        cb = self._hotkeys_changed_callback
        if cb is not None:
            try:
                cb()
            except Exception:
                import logging
                logging.getLogger("platex.script_base").exception("Error in hotkeys changed callback")

    def activate(self) -> None:
        pass

    def deactivate(self) -> None:
        if self._context is not None:
            try:
                self._context.shutdown()
            except Exception:
                pass
            self._context = None

    def load_config(self, config: dict[str, Any]) -> None:
        pass

    def save_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def _validate_config_path(path: Any) -> Path:
        from pathlib import Path
        p = Path(path) if not isinstance(path, Path) else path
        if ".." in p.parts:
            raise ValueError(f"Config path contains '..' segments (path traversal rejected): {p}")
        resolved = p.resolve()
        if p.is_symlink():
            raise ValueError(f"Config path is a symlink (not allowed): {p} -> {resolved}")
        return resolved

    def import_config(self, path: Any) -> dict[str, Any]:
        import yaml
        from pathlib import Path
        p = self._validate_config_path(path)
        if not p.exists():
            raise FileNotFoundError(f"Config file not found: {p}")
        if not p.is_file():
            raise ValueError(f"Config path is not a regular file: {p}")
        imported = yaml.safe_load(p.read_text(encoding="utf-8"))
        if imported is None:
            return {}
        if not isinstance(imported, dict):
            raise ValueError("Config file must contain a YAML mapping.")
        self.load_config(imported)
        return imported

    def export_config(self, path: Any) -> None:
        import yaml
        from pathlib import Path
        p = self._validate_config_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        config = self.save_config()
        config["__script_name__"] = self.name
        p.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False), encoding="utf-8")

    def has_ocr_capability(self) -> bool:
        return False

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        if self.has_ocr_capability():
            raise NotImplementedError(f"{self.name} must implement process_image()")
        raise RuntimeError(f"Script {self.name} does not have OCR capability")

    def get_tray_menu_items(self) -> list[TrayMenuItem]:
        return []

    def set_tray_action_callback(self, callback: Any | None) -> None:
        self._tray_action_callback = callback

    def test_connection(self) -> tuple[bool, str]:
        return True, "OK"
