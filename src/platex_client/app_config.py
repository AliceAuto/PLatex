from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("platex.config")


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


def parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in ("false", "0", "no", "off", "")
    return bool(value)


def _validate_config_path(value: str, field_name: str) -> Path | None:
    p = Path(value.strip())
    if not value.strip():
        return None
    if ".." in p.parts:
        logger.warning("Config path for '%s' contains '..' segments (rejected): %s", field_name, value)
        return None
    resolved = p.resolve()
    return resolved


def parse_payload_to_app_config(payload: dict[str, Any]) -> AppConfig:
    raw_interval = float(payload.get("interval", 0.8))
    if raw_interval <= 0:
        raw_interval = 0.8

    db_path = _validate_config_path(payload["db_path"], "db_path") if isinstance(payload.get("db_path"), str) and payload["db_path"].strip() else None
    script = _validate_config_path(payload["script"], "script") if isinstance(payload.get("script"), str) and payload["script"].strip() else None
    log_file = _validate_config_path(payload["log_file"], "log_file") if isinstance(payload.get("log_file"), str) and payload["log_file"].strip() else None

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
        db_path=db_path,
        script=script,
        log_file=log_file,
        interval=raw_interval,
        isolate_mode=parse_bool(payload.get("isolate_mode", False)),
        glm_api_key=payload.get("glm_api_key"),
        glm_model=payload.get("glm_model"),
        glm_base_url=payload.get("glm_base_url"),
        auto_start=parse_bool(payload.get("auto_start", False)),
        ui_language=str(payload.get("ui_language", "en")),
        language_pack=str(payload.get("language_pack", "")),
        scripts=raw_scripts,
    )


def load_file_payload(path: Path) -> dict[str, Any]:
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
    return payload


def app_config_to_dict(cfg: AppConfig) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result["config_version"] = cfg.config_version
    if cfg.db_path is not None:
        result["db_path"] = str(cfg.db_path)
    if cfg.script is not None:
        result["script"] = str(cfg.script)
    if cfg.log_file is not None:
        result["log_file"] = str(cfg.log_file)
    result["interval"] = cfg.interval
    result["isolate_mode"] = cfg.isolate_mode
    if cfg.glm_api_key is not None:
        result["glm_api_key"] = cfg.glm_api_key
    if cfg.glm_model is not None:
        result["glm_model"] = cfg.glm_model
    if cfg.glm_base_url is not None:
        result["glm_base_url"] = cfg.glm_base_url
    result["auto_start"] = cfg.auto_start
    result["ui_language"] = cfg.ui_language
    result["language_pack"] = cfg.language_pack
    result["scripts"] = cfg.scripts
    return result


def candidate_config_paths(config_path: Path | None) -> list[Path]:
    from .config_manager import config_file_path

    if config_path is not None:
        return [config_path]
    return [config_file_path()]
