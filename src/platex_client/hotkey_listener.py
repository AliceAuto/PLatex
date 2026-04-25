from __future__ import annotations

import logging
import threading
from typing import Callable

logger = logging.getLogger("platex.hotkeys")

_PYNPUT_AVAILABLE = False
try:
    from pynput import keyboard as _pynput_keyboard
    from pynput.mouse import Controller as _MouseController, Button as _MouseButton

    _PYNPUT_AVAILABLE = True
except ImportError:
    _pynput_keyboard = None  # type: ignore[assignment]
    _MouseController = None  # type: ignore[assignment]
    _MouseButton = None  # type: ignore[assignment]


def convert_hotkey_str(hotkey: str) -> str:
    """Convert a human-friendly hotkey string to pynput GlobalHotKeys format.

    "Ctrl+Alt+1"  ->  "<ctrl>+<alt>+1"
    "Ctrl+Shift+F5" -> "<ctrl>+<shift>+<f5>"
    """
    modifiers = {
        "ctrl": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "win": "<cmd>",
        "cmd": "<cmd>",
        "super": "<cmd>",
    }
    special_keys = {
        "space": "<space>",
        "enter": "<enter>",
        "return": "<enter>",
        "tab": "<tab>",
        "escape": "<escape>",
        "esc": "<escape>",
        "backspace": "<backspace>",
        "delete": "<delete>",
        "insert": "<insert>",
        "home": "<home>",
        "end": "<end>",
        "page_up": "<page_up>",
        "page_down": "<page_down>",
        "up": "<up>",
        "down": "<down>",
        "left": "<left>",
        "right": "<right>",
        "caps_lock": "<caps_lock>",
    }

    parts = hotkey.split("+")
    converted: list[str] = []
    for part in parts:
        key = part.strip().lower()
        if key in modifiers:
            converted.append(modifiers[key])
        elif key in special_keys:
            converted.append(special_keys[key])
        elif key.startswith("f") and key[1:].isdigit():
            converted.append(f"<{key}>")
        elif len(key) == 1 and key.isalnum():
            converted.append(key)
        else:
            converted.append(f"<{key}>")
    return "+".join(converted)


class HotkeyListener:
    """Global hotkey listener using pynput.

    Registers key combinations and dispatches callbacks when triggered.
    Supports dynamic registration and unregistration.
    """

    def __init__(self) -> None:
        self._bindings: dict[str, Callable[[], None]] = {}
        self._action_map: dict[str, str] = {}
        self._listener: object | None = None
        self._lock = threading.Lock()
        self._running = False
        self._suspended = False

    def register(self, hotkey: str, callback: Callable[[], None]) -> None:
        """Register a global hotkey with a callback.

        hotkey uses human-friendly format: "Ctrl+Alt+1".
        """
        with self._lock:
            pynput_key = convert_hotkey_str(hotkey)
            self._bindings[pynput_key] = callback
            self._rebuild_listener()

    def unregister(self, hotkey: str) -> None:
        """Unregister a global hotkey."""
        with self._lock:
            pynput_key = convert_hotkey_str(hotkey)
            self._bindings.pop(pynput_key, None)
            self._rebuild_listener()

    def clear(self) -> None:
        """Remove all hotkey bindings."""
        with self._lock:
            self._bindings.clear()
            self._action_map.clear()
            self._rebuild_listener()

    def start(self) -> None:
        """Start the global hotkey listener."""
        if not _PYNPUT_AVAILABLE:
            logger.warning("pynput not available; global hotkeys disabled")
            return
        self._running = True
        with self._lock:
            self._rebuild_listener()

    def stop(self) -> None:
        """Stop the global hotkey listener."""
        self._running = False
        with self._lock:
            self._stop_listener()

    def suspend(self) -> None:
        """Temporarily suspend hotkey processing (e.g., during position picking)."""
        self._suspended = True

    def resume(self) -> None:
        """Resume hotkey processing after suspend."""
        self._suspended = False

    def _rebuild_listener(self) -> None:
        """Stop the current listener and create a new one with current bindings."""
        self._stop_listener()

        if not _PYNPUT_AVAILABLE or not self._bindings or not self._running:
            return

        wrapped_bindings: dict[str, Callable[[], None]] = {}
        for pynput_key, cb in self._bindings.items():

            def _make_callback(callback: Callable[[], None]) -> Callable[[], None]:
                def _wrapped() -> None:
                    if not self._suspended:
                        try:
                            callback()
                        except Exception:  # noqa: BLE001
                            logger.exception("Error in hotkey callback")
                return _wrapped

            wrapped_bindings[pynput_key] = _make_callback(cb)

        try:
            self._listener = _pynput_keyboard.GlobalHotKeys(wrapped_bindings)
            self._listener.start()
            logger.info("Hotkey listener started with %d bindings", len(wrapped_bindings))
        except Exception as exc:
            logger.error("Failed to start hotkey listener: %s", exc)
            self._listener = None

    def _stop_listener(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


def simulate_click(x: int, y: int, button: str = "left") -> None:
    """Move mouse to (x, y), click, then restore original position."""
    if not _PYNPUT_AVAILABLE:
        logger.error("pynput not available; cannot simulate click")
        return

    try:
        mouse = _MouseController()
        original_pos = mouse.position
        btn = _MouseButton.left if button == "left" else _MouseButton.right
        mouse.position = (x, y)
        mouse.click(btn)
        mouse.position = original_pos
        logger.info("Simulated %s click at (%d, %d), restored to %s", button, x, y, original_pos)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to simulate click at (%d, %d)", x, y)