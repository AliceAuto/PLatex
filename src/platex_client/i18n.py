from __future__ import annotations

import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("platex.i18n")


def _resolve_locales_dir() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path.cwd()))
        candidate = base / "platex_client" / "locales"
        if candidate.is_dir():
            return candidate
    return Path(__file__).parent / "locales"


_locales_dir = _resolve_locales_dir()
_current_language: str = "en"
_translations: dict[str, dict[str, str]] = {}
_language_change_callbacks: list[Any] = []
_i18n_lock = threading.Lock()

_SAFE_FORMAT_RE = re.compile(r"\{(\w+)\}")


def _load_language_pack(language: str) -> dict[str, str]:
    lang_file = _locales_dir / f"{language}.yaml"
    if not lang_file.exists():
        logger.warning("Language pack not found: %s", lang_file)
        return {}

    try:
        with lang_file.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if isinstance(data, dict):
                return {k: str(v) for k, v in data.items() if isinstance(v, (str, int, float, bool))}
            return {}
    except Exception as exc:
        logger.error("Failed to load language pack %s: %s", language, exc)
        return {}


def initialize(language: str = "en") -> None:
    global _current_language, _translations

    with _i18n_lock:
        _current_language = language
        _translations = _load_language_pack(language)

        if not _translations and language != "en":
            logger.warning("Fallback to English for language: %s", language)
            _current_language = "en"
            _translations = _load_language_pack("en")

        logger.info("i18n initialized with language: %s (%d keys loaded)", _current_language, len(_translations))


def get_current_language() -> str:
    with _i18n_lock:
        return _current_language


def t(key: str, **kwargs: Any) -> str:
    with _i18n_lock:
        text = _translations.get(key, key)

    if kwargs:
        try:
            text = _SAFE_FORMAT_RE.sub(
                lambda m: str(kwargs.get(m.group(1), m.group(0))),
                text,
            )
        except Exception as exc:
            logger.debug("Translation format error for key '%s': %s", key, exc)

    return text


def switch_language(language: str) -> None:
    global _current_language, _translations

    with _i18n_lock:
        if language == _current_language:
            return

        new_translations = _load_language_pack(language)

        if not new_translations and language != "en":
            logger.warning("Language pack '%s' not found, keeping current language", language)
            return

        _current_language = language
        _translations = new_translations if new_translations else _load_language_pack("en")

        logger.info("Language switched to: %s", _current_language)

        callbacks = list(_language_change_callbacks)

    for callback in callbacks:
        try:
            callback(_current_language)
        except Exception as exc:
            logger.error("Language change callback error: %s", exc)


def on_language_changed(callback: Any) -> None:
    with _i18n_lock:
        _language_change_callbacks.append(callback)


def remove_language_callback(callback: Any) -> None:
    with _i18n_lock:
        if callback in _language_change_callbacks:
            _language_change_callbacks.remove(callback)


def available_languages() -> list[tuple[str, str]]:
    languages = [
        ("en", "English"),
        ("zh-cn", "中文（简体）"),
    ]

    available = []
    for code, name in languages:
        lang_file = _locales_dir / f"{code}.yaml"
        if lang_file.exists():
            available.append((code, name))

    return available
