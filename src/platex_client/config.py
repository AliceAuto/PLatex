from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .api_key_masking import fill_masked_api_keys, hide_api_key, restore_api_key
from .config_manager import config_file_path

logger = logging.getLogger("platex.config")

_hide_api_key = hide_api_key
_restore_api_key = restore_api_key
_fill_masked_api_keys = fill_masked_api_keys


@dataclass(slots=True)
class AppConfig:
    config_version: int = 0
    db_path: Path | None = None
    script: Path | None = None
    log_file: Path | None = None
    interval: float = 0.8
    isolate_mode: bool = False
    glm_api_key: str | None = None
    glm_model: str | None = None
    glm_base_url: str | None = None
    auto_start: bool = False
    ui_language: str = "en"
    language_pack: str = ""
    scripts: dict[str, Any] = field(default_factory=dict)

    def apply_environment(self) -> None:
        pass


def default_config_path() -> Path:
    return config_file_path()


def default_log_path() -> Path:
    from .config_manager import log_file_path
    return log_file_path()


def _candidate_config_paths(config_path: Path | None) -> list[Path]:
    if config_path is not None:
        return [config_path]
    return [config_file_path()]


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in ("false", "0", "no", "off", "")
    return bool(value)


def _validate_config_path(raw: str, *, allow_cwd_fallback: bool = True) -> Path | None:
    stripped = raw.strip()
    if not stripped:
        return None
    p = Path(stripped)
    if ".." in p.parts:
        logger.warning("Config path contains '..' segments (rejected): %s", stripped)
        return None
    resolved = p.resolve()
    return resolved


def _safe_resolve_path(value: str, field_name: str) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    p = Path(value.strip())
    if ".." in p.parts:
        logger.warning("Config path for '%s' contains '..' segments indicating path traversal: %s — rejected", field_name, value)
        return None
    return p.resolve()


_VALID_LANGUAGE_CODES = {"en", "zh-cn"}


def _is_valid_language_code(code: str) -> bool:
    return code in _VALID_LANGUAGE_CODES


def load_config(config_path: Path | None = None) -> AppConfig:
    path = next((candidate for candidate in _candidate_config_paths(config_path) if candidate.exists()), None)
    if path is None:
        cfg_path = config_file_path()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        empty_payload: dict[str, Any] = {"config_version": 0}
        try:
            cfg_path.write_text(
                yaml.safe_dump(empty_payload, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
        except OSError:
            logger.exception("Failed to create initial config file at %s", cfg_path)
        return AppConfig()

    try:
        with path.open("r", encoding="utf-8") as handle:
            if path.suffix.lower() == ".json":
                payload = json.load(handle)
            else:
                payload = yaml.safe_load(handle)
    except (yaml.YAMLError, json.JSONDecodeError, OSError) as exc:
        raise ValueError(f"Failed to load configuration from {path}: {exc}") from exc

    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration file must contain a mapping: {path}")

    try:
        raw_interval = float(payload.get("interval", 0.8))
    except (TypeError, ValueError):
        raw_interval = 0.8
    if raw_interval <= 0:
        raw_interval = 0.8
    raw_interval = max(0.1, min(raw_interval, 60.0))

    raw_language = str(payload.get("ui_language", "en")).strip().lower()
    if not _is_valid_language_code(raw_language):
        logger.warning("Invalid ui_language '%s' in config, defaulting to 'en'", raw_language)
        raw_language = "en"

    raw_scripts = payload.get("scripts")
    if not isinstance(raw_scripts, dict):
        raw_scripts = {}

    raw_config_version = 0
    try:
        raw_config_version = int(payload.get("config_version", 0))
    except (TypeError, ValueError):
        raw_config_version = 0

    return AppConfig(
        config_version=raw_config_version,
        db_path=_safe_resolve_path(payload.get("db_path", ""), "db_path"),
        script=_safe_resolve_path(payload.get("script", ""), "script"),
        log_file=_safe_resolve_path(payload.get("log_file", ""), "log_file"),
        interval=raw_interval,
        isolate_mode=_parse_bool(payload.get("isolate_mode", False)),
        glm_api_key=payload.get("glm_api_key"),
        glm_model=payload.get("glm_model"),
        glm_base_url=payload.get("glm_base_url"),
        auto_start=_parse_bool(payload.get("auto_start", False)),
        ui_language=raw_language,
        language_pack=str(payload.get("language_pack", "")),
        scripts=raw_scripts,
    )


class ConfigStore:
    _instance: ConfigStore | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self.config: AppConfig = load_config()
        self._disk_payload: dict[str, Any] = self._build_payload_from_config()
        self._ops_lock = threading.Lock()

    @classmethod
    def instance(cls) -> ConfigStore:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        with cls._lock:
            cls._instance = None

    def reload(self) -> None:
        with self._ops_lock:
            self.config = load_config()
            self._disk_payload = self._build_payload_from_config()

    def _build_payload_from_config(self) -> dict[str, Any]:
        cfg = self.config
        result: dict[str, Any] = {
            "config_version": cfg.config_version,
            "db_path": str(cfg.db_path) if cfg.db_path else "",
            "script": str(cfg.script) if cfg.script else "",
            "log_file": str(cfg.log_file) if cfg.log_file else "",
            "interval": cfg.interval,
            "isolate_mode": cfg.isolate_mode,
            "glm_api_key": cfg.glm_api_key or "",
            "glm_model": cfg.glm_model or "",
            "glm_base_url": cfg.glm_base_url or "",
            "auto_start": cfg.auto_start,
            "ui_language": cfg.ui_language,
            "language_pack": cfg.language_pack,
            "scripts": cfg.scripts,
        }
        return result

    def build_full_payload(self) -> dict[str, Any]:
        with self._ops_lock:
            return dict(self._disk_payload)

    def request_update_and_save(self, payload: dict[str, Any]) -> None:
        with self._ops_lock:
            from .api_key_masking import fill_masked_api_keys
            filled_payload = fill_masked_api_keys(payload, self._disk_payload)
            self._disk_payload.update(filled_payload)

            script_val = payload.get("script")
            if isinstance(script_val, str) and script_val.strip():
                resolved_script = _safe_resolve_path(script_val, "script")
                if resolved_script is not None:
                    self.config.script = resolved_script
                else:
                    logger.warning("Script path rejected due to path traversal: %s", script_val)

            interval_raw = payload.get("interval", self.config.interval)
            try:
                parsed_interval = float(interval_raw)
            except (TypeError, ValueError):
                parsed_interval = self.config.interval
            if parsed_interval < 0.1:
                logger.warning("Interval %.3f is too small, clamping to 0.1", parsed_interval)
                parsed_interval = 0.1
            if parsed_interval > 60.0:
                logger.warning("Interval %.3f is too large, clamping to 60.0", parsed_interval)
                parsed_interval = 60.0
            self.config.interval = parsed_interval

            self.config.isolate_mode = _parse_bool(payload.get("isolate_mode", self.config.isolate_mode))
            self.config.auto_start = _parse_bool(payload.get("auto_start", self.config.auto_start))
            ui_lang = str(payload.get("ui_language", self.config.ui_language)).strip().lower()
            if ui_lang and _is_valid_language_code(ui_lang):
                self.config.ui_language = ui_lang
            elif ui_lang:
                logger.warning("Invalid ui_language '%s', keeping '%s'", ui_lang, self.config.ui_language)

            db_path_val = payload.get("db_path")
            if isinstance(db_path_val, str) and db_path_val.strip():
                self.config.db_path = _safe_resolve_path(db_path_val, "db_path")

            log_file_val = payload.get("log_file")
            if isinstance(log_file_val, str) and log_file_val.strip():
                self.config.log_file = _safe_resolve_path(log_file_val, "log_file")

            glm_api_key = payload.get("glm_api_key")
            if isinstance(glm_api_key, str):
                self.config.glm_api_key = glm_api_key

            glm_model = payload.get("glm_model")
            if isinstance(glm_model, str):
                self.config.glm_model = glm_model

            glm_base_url = payload.get("glm_base_url")
            if isinstance(glm_base_url, str):
                self.config.glm_base_url = glm_base_url

            config_version = payload.get("config_version")
            if isinstance(config_version, int):
                self.config.config_version = config_version

            language_pack = payload.get("language_pack")
            if isinstance(language_pack, str):
                self.config.language_pack = language_pack

            scripts = payload.get("scripts")
            if isinstance(scripts, dict):
                self.config.scripts = scripts

            self._save_to_disk()

    def _save_to_disk(self) -> None:
        try:
            text = yaml.safe_dump(self._disk_payload, sort_keys=False, allow_unicode=True)
            cfg_path = config_file_path()
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = cfg_path.with_suffix(".yaml.tmp")
            try:
                tmp_path.write_text(text, encoding="utf-8")
                tmp_path.replace(cfg_path)
            except OSError:
                logger.exception("Atomic config save failed, attempting direct write as fallback")
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass
                try:
                    cfg_path.write_text(text, encoding="utf-8")
                except Exception:
                    logger.exception("Failed to save config file even with direct write")
        except Exception:
            logger.exception("Failed to save configuration to disk")
            return
        try:
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.CreateFileW(
                    str(cfg_path), 0x00010000, 0, None, 3, 0x80, None
                )
                if handle != -1:
                    kernel32.CloseHandle(handle)
            else:
                import stat
                os.chmod(cfg_path, stat.S_IRUSR | stat.S_IWUSR)
        except Exception:
            logger.debug("Failed to set restrictive permissions on config file", exc_info=True)

    def build_disk_yaml_text(self) -> str:
        return yaml.safe_dump(self._disk_payload, sort_keys=False, allow_unicode=True)
