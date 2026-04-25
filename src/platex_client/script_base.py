from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from PyQt6.QtWidgets import QWidget


class ScriptBase(ABC):
    """Base class for all PLatex scripts.

    Each script can optionally:
    - Provide a settings UI widget (create_settings_widget)
    - Register global hotkeys (get_hotkey_bindings / on_hotkey)
    - Process clipboard images (has_ocr_capability / process_image)
    - Persist its own configuration (load_config / save_config)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this script (used in config and registry)."""

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name shown in the UI."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Short description of what this script does."""

    def create_settings_widget(self, parent: QWidget | None = None) -> QWidget | None:
        """Create and return a QWidget for this script's settings page.

        The returned widget will be placed inside a tab in the Control Panel.
        Return None if the script has no settings UI.
        """
        return None

    def get_hotkey_bindings(self) -> dict[str, str]:
        """Return hotkey bindings as {hotkey_str: action_name}.

        hotkey_str uses human-friendly format: "Ctrl+Alt+1", "Ctrl+Shift+F5".
        The on_hotkey method will be called with the corresponding action_name
        when the hotkey is triggered.
        """
        return {}

    def on_hotkey(self, action: str) -> None:
        """Called when a registered hotkey is triggered."""

    def activate(self) -> None:
        """Called when the script is activated (started)."""

    def deactivate(self) -> None:
        """Called when the script is deactivated (stopped)."""

    def load_config(self, config: dict[str, Any]) -> None:
        """Load script-specific configuration from a dict."""

    def save_config(self) -> dict[str, Any]:
        """Return script-specific configuration as a dict for persistence."""
        return {}

    def has_ocr_capability(self) -> bool:
        """Whether this script can process clipboard images (OCR)."""
        return False

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        """Process a clipboard image and return LaTeX text.

        Only called when has_ocr_capability() returns True.
        """
        raise NotImplementedError