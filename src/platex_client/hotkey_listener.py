from __future__ import annotations

import logging
import threading
import time
from typing import Callable

from .platform_utils import IS_WINDOWS, USER32

logger = logging.getLogger("platex.hotkeys")

_PYNPUT_AVAILABLE = False
try:
    from pynput import keyboard as _pynput_keyboard

    _PYNPUT_AVAILABLE = True
except ImportError:
    _pynput_keyboard = None  # type: ignore[assignment]


def convert_hotkey_str(hotkey: str) -> str:
    if not hotkey or not hotkey.strip():
        raise ValueError(f"Invalid hotkey string: {hotkey!r}")

    modifiers = {
        "ctrl": "<ctrl>",
        "control": "<ctrl>",
        "alt": "<alt>",
        "shift": "<shift>",
        "win": "<cmd>",
        "cmd": "<cmd>",
        "super": "<cmd>",
        "meta": "<cmd>",
        "windows": "<cmd>",
    }
    special_keys = {
        "space": "<space>",
        "enter": "<enter>",
        "return": "<enter>",
        "tab": "<tab>",
        "backtab": "<backtab>",
        "escape": "<escape>",
        "esc": "<escape>",
        "backspace": "<backspace>",
        "delete": "<delete>",
        "del": "<delete>",
        "insert": "<insert>",
        "ins": "<insert>",
        "home": "<home>",
        "end": "<end>",
        "page_up": "<page_up>",
        "pgup": "<page_up>",
        "prior": "<page_up>",
        "page_down": "<page_down>",
        "pgdown": "<page_down>",
        "pgdn": "<page_down>",
        "next": "<page_down>",
        "up": "<up>",
        "down": "<down>",
        "left": "<left>",
        "right": "<right>",
        "caps_lock": "<caps_lock>",
        "capslock": "<caps_lock>",
        "num_lock": "<num_lock>",
        "number_lock": "<num_lock>",
        "numlock": "<num_lock>",
        "scroll_lock": "<scroll_lock>",
        "scrolllock": "<scroll_lock>",
        "print_screen": "<print_screen>",
        "sysrq": "<print_screen>",
        "system_request": "<print_screen>",
        "prtsc": "<print_screen>",
        "pause": "<pause>",
        "break": "<pause>",
        "menu": "<menu>",
        "help": "<help>",
        "clear": "<clear>",
        "print": "<print>",
        "volume_down": "<volume_down>",
        "volume_mute": "<volume_mute>",
        "volume_up": "<volume_up>",
        "bass_boost": "<bass_boost>",
        "bass_up": "<bass_up>",
        "bass_down": "<bass_down>",
        "treble_up": "<treble_up>",
        "treble_down": "<treble_down>",
        "media_play": "<media_play>",
        "media_stop": "<media_stop>",
        "media_previous": "<media_previous>",
        "media_next": "<media_next>",
        "media_record": "<media_record>",
        "media_pause": "<media_pause>",
        "media_rewind": "<media_rewind>",
        "media_fast_forward": "<media_fast_forward>",
        "home_page": "<home_page>",
        "open_url": "<open_url>",
        "launch_mail": "<launch_mail>",
        "launch_media": "<launch_media>",
        "monitor_brightness_up": "<monitor_brightness_up>",
        "monitor_brightness_down": "<monitor_brightness_down>",
        "keyboard_light_on/off": "<keyboard_light_on/off>",
        "keyboard_brightness_up": "<keyboard_brightness_up>",
        "keyboard_brightness_down": "<keyboard_brightness_down>",
        "power_off": "<power_off>",
        "wake_up": "<wake_up>",
        "adjust_brightness": "<adjust_brightness>",
        "adjust_contrast": "<adjust_contrast>",
        "back_forward": "<back_forward>",
        "application_left": "<application_left>",
        "application_right": "<application_right>",
        "clear_grab": "<clear_grab>",
        "keyboard_menu": "<keyboard_menu>",
        "menu_pb": "<menu_pb>",
        "my_sites": "<my_sites>",
        "home_office": "<home_office>",
        "rotate_windows": "<rotate_windows>",
        "rotation_pb": "<rotation_pb>",
        "rotation_kb": "<rotation_kb>",
        "split_screen": "<split_screen>",
        "task_panel": "<task_panel>",
        "to-do_list": "<to-do_list>",
        "word_processor": "<word_processor>",
        "mail_forward": "<mail_forward>",
        "ultra_wide_band": "<ultra_wide_band>",
        "audio_repeat": "<audio_repeat>",
        "audio_random_play": "<audio_random_play>",
        "audio_cycle_track": "<audio_cycle_track>",
        "top_menu": "<top_menu>",
        "power_down": "<power_down>",
        "microphone_mute": "<microphone_mute>",
        "channel_up": "<channel_up>",
        "channel_down": "<channel_down>",
        "microphone_volume_up": "<microphone_volume_up>",
        "microphone_volume_down": "<microphone_volume_down>",
        "toggle_media_play/pause": "<toggle_media_play/pause>",
        "toggle_call/hangup": "<toggle_call/hangup>",
        "last_number_redial": "<last_number_redial>",
        "camera_shutter": "<camera_shutter>",
        "camera_focus": "<camera_focus>",
        "hangul_start": "<hangul_start>",
        "hangul_end": "<hangul_end>",
        "hangul_hanja": "<hangul_hanja>",
        "hangul_jamo": "<hangul_jamo>",
        "hangul_romaja": "<hangul_romaja>",
        "hangul_jeonja": "<hangul_jeonja>",
        "hangul_banja": "<hangul_banja>",
        "hangul_prehanja": "<hangul_prehanja>",
        "hangul_posthanja": "<hangul_posthanja>",
        "hangul_special": "<hangul_special>",
        "hiragana_katakana": "<hiragana_katakana>",
        "zenkaku_hankaku": "<zenkaku_hankaku>",
        "kana_lock": "<kana_lock>",
        "kana_shift": "<kana_shift>",
        "eisu_shift": "<eisu_shift>",
        "eisu_toggle": "<eisu_toggle>",
        "code_input": "<code_input>",
        "multiple_candidate": "<multiple_candidate>",
        "previous_candidate": "<previous_candidate>",
        "add_favorite": "<add_favorite>",
        "hot_links": "<hot_links>",
        "light_bulb": "<light_bulb>",
        "touchpad_toggle": "<touchpad_toggle>",
        "touchpad_on": "<touchpad_on>",
        "touchpad_off": "<touchpad_off>",
        "browser_back": "<browser_back>",
        "browser_forward": "<browser_forward>",
        "browser_refresh": "<browser_refresh>",
        "browser_stop": "<browser_stop>",
        "browser_search": "<browser_search>",
        "browser_favorites": "<browser_favorites>",
        "browser_home": "<browser_home>",
        "favorites": "<favorites>",
        "search": "<search>",
        "standby": "<standby>",
        "sleep": "<sleep>",
        "eject": "<eject>",
        "screensaver": "<screensaver>",
        "www": "<www>",
        "calculator": "<calculator>",
        "calendar": "<calendar>",
        "close": "<close>",
        "copy": "<copy>",
        "cut": "<cut>",
        "paste": "<paste>",
        "save": "<save>",
        "send": "<send>",
        "spellchecker": "<spellchecker>",
        "support": "<support>",
        "terminal": "<terminal>",
        "tools": "<tools>",
        "travel": "<travel>",
        "video": "<video>",
        "zoom_in": "<zoom_in>",
        "zoom_out": "<zoom_out>",
        "away": "<away>",
        "messenger": "<messenger>",
        "webcam": "<webcam>",
        "pictures": "<pictures>",
        "music": "<music>",
        "battery": "<battery>",
        "bluetooth": "<bluetooth>",
        "wireless": "<wireless>",
        "subtitle": "<subtitle>",
        "time": "<time>",
        "hibernate": "<hibernate>",
        "view": "<view>",
        "suspend": "<suspend>",
        "red": "<red>",
        "green": "<green>",
        "yellow": "<yellow>",
        "blue": "<blue>",
        "guide": "<guide>",
        "info": "<info>",
        "settings": "<settings>",
        "new": "<new>",
        "open": "<open>",
        "find": "<find>",
        "undo": "<undo>",
        "redo": "<redo>",
        "cancel": "<cancel>",
        "printer": "<printer>",
        "execute": "<execute>",
        "play": "<play>",
        "zoom": "<zoom>",
        "exit": "<exit>",
        "select": "<select>",
        "yes": "<yes>",
        "no": "<no>",
        "call": "<call>",
        "hangup": "<hangup>",
        "flip": "<flip>",
        "voice_dial": "<voice_dial>",
        "context1": "<context1>",
        "context2": "<context2>",
        "context3": "<context3>",
        "context4": "<context4>",
        "hangul": "<hangul>",
        "kanji": "<kanji>",
        "muhenkan": "<muhenkan>",
        "henkan": "<henkan>",
        "romaji": "<romaji>",
        "hiragana": "<hiragana>",
        "katakana": "<katakana>",
        "zenkaku": "<zenkaku>",
        "hankaku": "<hankaku>",
        "touroku": "<touroku>",
        "massyo": "<massyo>",
    }

    _MULTI_WORD_KEYS = [
        "page up", "page down", "caps lock", "num lock", "number lock",
        "scroll lock", "print screen", "system request", "volume down",
        "volume mute", "volume up", "bass boost", "bass up", "bass down",
        "treble up", "treble down", "media play", "media stop",
        "media previous", "media next", "media record", "media pause",
        "media rewind", "media fast forward", "home page", "open url",
        "launch mail", "launch media", "monitor brightness up",
        "monitor brightness down", "keyboard light on/off",
        "keyboard brightness up", "keyboard brightness down",
        "power off", "wake up", "adjust brightness", "adjust contrast",
        "back forward", "application left", "application right",
        "clear grab", "keyboard menu", "menu pb", "my sites",
        "home office", "rotate windows", "rotation pb", "rotation kb",
        "split screen", "task panel", "to-do list", "word processor",
        "mail forward", "ultra wide band", "audio repeat",
        "audio random play", "audio cycle track", "top menu",
        "power down", "microphone mute", "channel up", "channel down",
        "microphone volume up", "microphone volume down",
        "toggle media play/pause", "toggle call/hangup",
        "last number redial", "camera shutter", "camera focus",
        "hangul start", "hangul end", "hangul hanja", "hangul jamo",
        "hangul romaja", "hangul jeonja", "hangul banja",
        "hangul prehanja", "hangul posthanja", "hangul special",
        "hiragana katakana", "zenkaku hankaku", "kana lock",
        "kana shift", "eisu shift", "eisu toggle", "code input",
        "multiple candidate", "previous candidate", "number lock",
        "add favorite", "hot links", "light bulb",
        "touchpad toggle", "touchpad on", "touchpad off",
        "browser back", "browser forward", "browser refresh",
        "browser stop", "browser search", "browser favorites",
        "browser home", "zoom in", "zoom out",
    ]

    normalized = hotkey.lower()
    for mw in _MULTI_WORD_KEYS:
        normalized = normalized.replace(mw, mw.replace(" ", "_"))

    _COMMA_KEY_PH = "\x00CK\x00"
    _PLUS_KEY_PH = "\x00PK\x00"

    normalized = normalized.replace("+,", _COMMA_KEY_PH)

    normalized = normalized.split(",", 1)[0].strip()

    normalized = normalized.replace(_COMMA_KEY_PH, "+,")

    while "++" in normalized:
        normalized = normalized.replace("++", "+" + _PLUS_KEY_PH)

    if normalized.endswith("+"):
        raise ValueError(f"Trailing '+' in hotkey string: {hotkey!r}")

    parts = normalized.split("+")
    parts = [p.replace(_PLUS_KEY_PH, "+").replace(_COMMA_KEY_PH, ",") for p in parts]

    _SPECIAL_CHARS = {"+", "=", "-", ","}

    converted: list[str] = []
    for part in parts:
        key = part.strip().lower()
        if not key:
            raise ValueError(f"Empty key segment in hotkey string: {hotkey!r}")
        if key in modifiers:
            converted.append(modifiers[key])
        elif key in special_keys:
            converted.append(special_keys[key])
        elif key.startswith("f") and key[1:].isdigit():
            converted.append(f"<{key}>")
        elif len(key) == 1 and key.isalnum():
            converted.append(key)
        elif key in _SPECIAL_CHARS:
            converted.append(f"<{key}>")
        else:
            converted.append(f"<{key}>")
    return "+".join(converted)


class _PynputBackend:
    def __init__(self, active: threading.Event) -> None:
        self._bindings: dict[str, Callable[[], None]] = {}
        self._listener: object | None = None
        self._active = active

    def set_bindings(self, bindings: dict[str, Callable[[], None]]) -> None:
        self._bindings = dict(bindings)

    def start(self) -> bool:
        if not _PYNPUT_AVAILABLE:
            return False
        self.stop()
        if not self._bindings:
            return True

        wrapped_bindings: dict[str, Callable[[], None]] = {}
        for pynput_key, cb in self._bindings.items():
            def _make_callback(callback: Callable[[], None]) -> Callable[[], None]:
                def _wrapped() -> None:
                    if not self._active.is_set():
                        return
                    try:
                        callback()
                    except Exception:  # noqa: BLE001
                        logger.exception("Error in hotkey callback")
                return _wrapped
            wrapped_bindings[pynput_key] = _make_callback(cb)

        try:
            self._listener = _pynput_keyboard.GlobalHotKeys(wrapped_bindings)
            self._listener.start()
            logger.info("pynput hotkey listener started with %d bindings", len(wrapped_bindings))
            return True
        except Exception as exc:
            logger.error("Failed to start pynput hotkey listener: %s", exc)
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception as exc:
                logger.debug("Failed to stop pynput listener cleanly: %s", exc)
            self._listener = None


class HotkeyListener:
    def __init__(self) -> None:
        self._bindings: dict[str, Callable[[], None]] = {}
        self._lock = threading.RLock()
        self._running = False
        self._active = threading.Event()
        self._active.set()
        self._win32_backend: Any | None = None
        self._pynput_backend: _PynputBackend | None = None
        self._use_win32 = False
        self._failed_bindings: dict[str, int] = {}
        self._retry_timer: threading.Timer | None = None
        self._retry_count: int = 0
        self._max_retries: int = 20
        self._status_callbacks: list[Callable[[dict], None]] = []
        self._batch_depth: int = 0
        self._passthrough_bindings: dict[str, Callable[[], None]] = {}
        self._ll_hook: Any | None = None

        if IS_WINDOWS:
            try:
                from .win32_hotkey import Win32HotkeyListener
                self._win32_backend = Win32HotkeyListener()
            except Exception as exc:
                logger.debug("Win32 hotkey backend not available: %s", exc)

        if _PYNPUT_AVAILABLE:
            self._pynput_backend = _PynputBackend(self._active)

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        with self._lock:
            self._bindings[hotkey] = callback
            self._failed_bindings.pop(hotkey, None)
            if self._batch_depth > 0:
                return True
            if self._running and self._use_win32 and self._win32_backend is not None:
                try:
                    pynput_key = convert_hotkey_str(hotkey)
                except ValueError:
                    pynput_key = hotkey
                success = self._win32_backend.register(pynput_key, callback)
                if not success:
                    self._failed_bindings[hotkey] = self._failed_bindings.get(hotkey, 0) + 1
                else:
                    self._failed_bindings.pop(hotkey, None)
                self._notify_status()
                return success
        return self._rebuild_listener()

    def register_many(self, bindings: dict[str, Callable[[], None]]) -> bool:
        with self._lock:
            for hotkey, callback in bindings.items():
                self._bindings[hotkey] = callback
                self._failed_bindings.pop(hotkey, None)
            if self._batch_depth > 0:
                return True
        return self._rebuild_listener()

    def unregister(self, hotkey: str) -> None:
        with self._lock:
            self._bindings.pop(hotkey, None)
            self._failed_bindings.pop(hotkey, None)
            if self._batch_depth > 0:
                return
            if self._running and self._use_win32 and self._win32_backend is not None:
                try:
                    pynput_key = convert_hotkey_str(hotkey)
                except ValueError:
                    pynput_key = hotkey
                self._win32_backend.unregister(pynput_key)
                self._notify_status()
                return
        self._rebuild_listener()

    def clear(self) -> None:
        with self._lock:
            self._bindings.clear()
            self._failed_bindings.clear()
            self._passthrough_bindings.clear()
            self._cancel_retry()
            if self._win32_backend is not None:
                self._win32_backend.clear()
            if self._pynput_backend is not None:
                self._pynput_backend.set_bindings({})
                self._pynput_backend.stop()
            if self._ll_hook is not None:
                self._ll_hook.clear()
                self._ll_hook.stop()
                self._ll_hook = None

    def start(self) -> None:
        self._running = True
        self._rebuild_listener()
        self._rebuild_passthrough()

    def stop(self) -> None:
        self._running = False
        self._cancel_retry()
        with self._lock:
            if self._win32_backend is not None:
                self._win32_backend.stop()
            if self._pynput_backend is not None:
                self._pynput_backend.stop()
            if self._ll_hook is not None:
                self._ll_hook.stop()
                self._ll_hook = None

    def suspend(self) -> None:
        self._active.clear()

    def resume(self) -> None:
        self._active.set()

    def batch_begin(self) -> None:
        with self._lock:
            self._batch_depth += 1

    def batch_end(self) -> None:
        with self._lock:
            self._batch_depth = max(0, self._batch_depth - 1)
        if self._running:
            self._rebuild_listener()
            self._rebuild_passthrough()

    def register_passthrough(self, hotkey: str, callback: Callable[[], None]) -> bool:
        with self._lock:
            self._passthrough_bindings[hotkey] = callback
            if self._batch_depth > 0:
                return True
        if self._running:
            self._rebuild_passthrough()
        return True

    def unregister_passthrough(self, hotkey: str) -> None:
        with self._lock:
            self._passthrough_bindings.pop(hotkey, None)
            if self._batch_depth > 0:
                return
        if self._running:
            self._rebuild_passthrough()

    def _rebuild_passthrough(self) -> None:
        if not IS_WINDOWS:
            return

        try:
            from .win32_hotkey import LowLevelKeyboardHook, _parse_hotkey_to_vk
        except ImportError:
            logger.warning("LowLevelKeyboardHook not available for passthrough hotkeys")
            return

        with self._lock:
            bindings_snapshot = dict(self._passthrough_bindings)
            active_event = self._active

        if not bindings_snapshot:
            if self._ll_hook is not None:
                self._ll_hook.stop()
                self._ll_hook = None
            return

        if self._ll_hook is None:
            self._ll_hook = LowLevelKeyboardHook()

        self._ll_hook.clear()

        for hotkey, callback in bindings_snapshot.items():
            try:
                pynput_key = convert_hotkey_str(hotkey)
            except ValueError:
                logger.error("Invalid passthrough hotkey '%s'", hotkey)
                continue

            parsed = _parse_hotkey_to_vk(pynput_key)
            if parsed is None:
                logger.error("Failed to parse passthrough hotkey '%s'", hotkey)
                continue

            modifiers, vk = parsed

            def _make_active_cb(cb: Callable[[], None], evt: threading.Event) -> Callable[[], None]:
                def _wrapped() -> None:
                    if not evt.is_set():
                        return
                    cb()
                return _wrapped

            wrapped = _make_active_cb(callback, active_event)
            self._ll_hook.register(modifiers, vk, wrapped)

        self._ll_hook.start()
        logger.info("Passthrough hotkey hook rebuilt with %d bindings", len(bindings_snapshot))

    def get_status(self) -> dict:
        with self._lock:
            return self._get_status_unlocked()

    def _get_status_unlocked(self) -> dict:
        status = {
            "running": self._running,
            "suspended": not self._active.is_set(),
            "backend": "win32" if self._use_win32 else ("pynput" if self._pynput_backend else "none"),
            "registered_count": len(self._bindings),
            "failed": dict(self._failed_bindings),
            "bindings": list(self._bindings.keys()),
        }
        if self._win32_backend is not None:
            try:
                win32_status = self._win32_backend.get_status()
                status["win32"] = win32_status
            except Exception:
                pass
        return status

    def on_status_change(self, callback: Callable[[dict], None]) -> None:
        with self._lock:
            self._status_callbacks.append(callback)

    def _notify_status(self) -> None:
        status = self._get_status_unlocked()
        callbacks = list(self._status_callbacks)
        for cb in callbacks:
            try:
                cb(status)
            except Exception:
                logger.exception("Error in status callback")

    def _rebuild_listener(self) -> bool:
        if not self._running:
            return True

        try:
            return self._do_rebuild_listener()
        except Exception:
            logger.exception("Unexpected error in _rebuild_listener")
            with self._lock:
                self._notify_status()
            return False

    def _do_rebuild_listener(self) -> bool:
        with self._lock:
            bindings_snapshot = dict(self._bindings)
            win32_backend = self._win32_backend
            pynput_backend = self._pynput_backend
            active_event = self._active

        if win32_backend is not None and IS_WINDOWS:
            self._use_win32 = True

            win32_thread_alive = False
            current_win32_keys: set[str] = set()
            try:
                win32_status = win32_backend.get_status()
                win32_thread_alive = win32_status.get("running", False)
                current_win32_keys = set(win32_status.get("registered", []))
            except Exception:
                current_win32_keys = set()

            if not win32_thread_alive and current_win32_keys:
                logger.warning("Win32 hotkey backend thread is dead, doing full rebuild")
                win32_backend.clear()
                current_win32_keys = set()

            desired_win32_keys: set[str] = set()
            for hotkey in bindings_snapshot:
                try:
                    pynput_key = convert_hotkey_str(hotkey)
                    desired_win32_keys.add(pynput_key)
                except ValueError:
                    pass

            keys_to_unregister = current_win32_keys - desired_win32_keys
            for pynput_key in keys_to_unregister:
                try:
                    win32_backend.unregister(pynput_key)
                except Exception:
                    logger.debug("Failed to unregister stale hotkey: %s", pynput_key)

            register_failed_keys: set[str] = set()
            for hotkey, callback in bindings_snapshot.items():
                try:
                    pynput_key = convert_hotkey_str(hotkey)
                except ValueError as exc:
                    logger.error("Invalid hotkey '%s': %s", hotkey, exc)
                    with self._lock:
                        self._failed_bindings[hotkey] = self._failed_bindings.get(hotkey, 0) + 1
                    register_failed_keys.add(hotkey)
                    continue
                if pynput_key not in current_win32_keys:
                    def _make_active_cb(cb: Callable[[], None], evt: threading.Event) -> Callable[[], None]:
                        def _wrapped() -> None:
                            if not evt.is_set():
                                return
                            cb()
                        return _wrapped
                    wrapped = _make_active_cb(callback, active_event)
                    ok = win32_backend.register(pynput_key, wrapped)
                    if not ok:
                        register_failed_keys.add(hotkey)
                        with self._lock:
                            self._failed_bindings[hotkey] = self._failed_bindings.get(hotkey, 0) + 1
                        logger.warning("Win32 register() failed for hotkey: %s (parse error)", hotkey)

            try:
                win32_backend.start()
            except Exception as exc:
                logger.error("Win32 hotkey backend start failed: %s", exc)

            try:
                win32_status = win32_backend.get_status()
                failed_win32 = win32_status.get("failed", {})
            except Exception:
                failed_win32 = {}

            all_success = True
            with self._lock:
                for hotkey in bindings_snapshot:
                    try:
                        pynput_key = convert_hotkey_str(hotkey)
                    except ValueError:
                        pynput_key = hotkey
                    if pynput_key in failed_win32 or hotkey in self._failed_bindings:
                        self._failed_bindings[hotkey] = self._failed_bindings.get(hotkey, 0) + 1
                        all_success = False
                        logger.warning("Failed to register Win32 hotkey: %s", hotkey)
                    else:
                        self._failed_bindings.pop(hotkey, None)
                self._notify_status()

            if all_success:
                if pynput_backend is not None:
                    pynput_backend.stop()
                self._retry_count = 0
                self._cancel_retry()
                return True
            else:
                if pynput_backend is not None:
                    pynput_fallback: dict[str, Callable[[], None]] = {}
                    for hotkey, callback in bindings_snapshot.items():
                        try:
                            pynput_key = convert_hotkey_str(hotkey)
                        except ValueError:
                            continue
                        if pynput_key in failed_win32 or hotkey in self._failed_bindings:
                            pynput_fallback[pynput_key] = callback
                    if pynput_fallback:
                        pynput_backend.set_bindings(pynput_fallback)
                        pynput_backend.start()
                        logger.info("Started pynput fallback for %d failed Win32 hotkeys", len(pynput_fallback))

                if win32_backend is not None:
                    win32_backend.schedule_retry()
                else:
                    self._schedule_retry()
                return False

        if pynput_backend is not None:
            self._use_win32 = False
            pynput_bindings: dict[str, Callable[[], None]] = {}
            for hotkey, callback in bindings_snapshot.items():
                try:
                    pynput_key = convert_hotkey_str(hotkey)
                    pynput_bindings[pynput_key] = callback
                except ValueError as exc:
                    logger.error("Invalid hotkey '%s': %s", hotkey, exc)
                    with self._lock:
                        self._failed_bindings[hotkey] = self._failed_bindings.get(hotkey, 0) + 1

            pynput_backend.set_bindings(pynput_bindings)
            success = pynput_backend.start()
            with self._lock:
                self._notify_status()
            return success

        logger.warning("No hotkey backend available")
        with self._lock:
            self._notify_status()
        return False

    def _schedule_retry(self) -> None:
        self._cancel_retry()
        with self._lock:
            if not self._failed_bindings or not self._running:
                return

            self._retry_count += 1
            if self._retry_count > self._max_retries:
                logger.warning(
                    "Reached max hotkey retry attempts (%d), giving up on: %s",
                    self._max_retries, list(self._failed_bindings.keys()),
                )
                self._retry_count = 0
                return

        delay = min(3.0 * (1.5 ** min(self._retry_count - 1, 6)), 30.0)

        def _retry() -> None:
            with self._lock:
                if not self._running:
                    return
            self._rebuild_listener()

        self._retry_timer = threading.Timer(delay, _retry)
        self._retry_timer.daemon = True
        self._retry_timer.start()
        logger.debug("Scheduled hotkey retry #%d in %.1fs for: %s", self._retry_count, delay, list(self._failed_bindings.keys()))

    def _cancel_retry(self) -> None:
        if self._retry_timer is not None:
            self._retry_timer.cancel()
            self._retry_timer = None


def simulate_click(x: int, y: int, button: str = "left") -> None:
    from .mouse_input import simulate_click as _mouse_simulate_click
    _mouse_simulate_click(x, y, button)
