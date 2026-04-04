from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from platformdirs import user_config_dir


@dataclass(slots=True)
class AppConfig:
    db_path: Path | None = None
    script: Path | None = None
    log_file: Path | None = None
    interval: float = 0.8
    publish_latex: bool = False
    isolate_mode: bool = False
    restore_delay: float = 0.25
    glm_api_key: str | None = None
    glm_model: str | None = None
    glm_base_url: str | None = None

    def apply_environment(self) -> None:
        if self.glm_api_key and not os.getenv("GLM_API_KEY"):
            os.environ["GLM_API_KEY"] = self.glm_api_key
        if self.glm_model and not os.getenv("GLM_MODEL"):
            os.environ["GLM_MODEL"] = self.glm_model
        if self.glm_base_url and not os.getenv("GLM_BASE_URL"):
            os.environ["GLM_BASE_URL"] = self.glm_base_url


def default_config_path() -> Path:
    return Path(user_config_dir("PLatexClient", "Copilot")) / "config.yaml"


def default_log_path() -> Path:
    return Path(user_config_dir("PLatexClient", "Copilot")) / "logs" / "platex-client.log"


def _candidate_config_paths(config_path: Path | None) -> list[Path]:
    if config_path is not None:
        return [config_path]

    cwd = Path.cwd()
    return [
        cwd / "config.yaml",
        cwd / "config.example.yaml",
        default_config_path(),
    ]


def load_config(config_path: Path | None = None) -> AppConfig:
    path = next((candidate for candidate in _candidate_config_paths(config_path) if candidate.exists()), None)
    if path is None:
        return AppConfig()

    with path.open("r", encoding="utf-8") as handle:
        if path.suffix.lower() == ".json":
            payload = json.load(handle)
        else:
            payload = yaml.safe_load(handle)

    payload = payload or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Configuration file must contain a mapping: {path}")

    return AppConfig(
        db_path=Path(payload["db_path"]) if payload.get("db_path") else None,
        script=Path(payload["script"]) if payload.get("script") else None,
        log_file=Path(payload["log_file"]) if payload.get("log_file") else None,
        interval=float(payload.get("interval", 0.8)),
        publish_latex=bool(payload.get("publish_latex", False)),
        isolate_mode=bool(payload.get("isolate_mode", False)),
        restore_delay=float(payload.get("restore_delay", 0.25)),
        glm_api_key=payload.get("glm_api_key"),
        glm_model=payload.get("glm_model"),
        glm_base_url=payload.get("glm_base_url"),
    )
