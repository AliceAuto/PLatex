from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("platex.config_manager")

_REGISTRY_KEY = r"Software\PLatexClient"
_REGISTRY_VALUE = "ConfigDir"


def _default_config_dir() -> Path:
    """Return the default config directory (%APPDATA%\\PLatexClient)."""
    from platformdirs import user_config_dir
    return Path(user_config_dir("PLatexClient", "Copilot"))


def get_config_dir() -> Path:
    """Resolve the active config directory.

    Priority:
    1. PLATEX_CONFIG_DIR environment variable
    2. Windows registry override (HKCU\\Software\\PLatexClient\\ConfigDir)
    3. Default (%APPDATA%\\PLatexClient)
    """
    env_dir = os.getenv("PLATEX_CONFIG_DIR")
    if env_dir:
        p = Path(env_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p

    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY, 0, winreg.KEY_READ) as key:
                value, _ = winreg.QueryValueEx(key, _REGISTRY_VALUE)
                if isinstance(value, str) and value.strip():
                    return Path(value.strip())
        except (FileNotFoundError, OSError):
            pass

    return _default_config_dir()


def set_config_dir(path: Path) -> None:
    """Persist a custom config directory path.

    On Windows this writes to HKCU\\Software\\PLatexClient\\ConfigDir.
    Also creates the directory if it does not exist.
    """
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)

    if os.name == "nt":
        import winreg
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REGISTRY_KEY) as key:
                winreg.SetValueEx(key, _REGISTRY_VALUE, 0, winreg.REG_SZ, str(path))
        except OSError as exc:
            logger.error("Failed to write config dir to registry: %s", exc)

    os.environ["PLATEX_CONFIG_DIR"] = str(path)


def config_file_path() -> Path:
    """Return the path to config.yaml in the active config directory."""
    return get_config_dir() / "config.yaml"


def db_file_path() -> Path:
    """Return the path to history.sqlite3 in the active config directory."""
    return get_config_dir() / "history.sqlite3"


def log_file_path() -> Path:
    """Return the path to the log file in the active config directory."""
    return get_config_dir() / "logs" / "platex-client.log"


class ConfigManager:
    """High-level config export/import manager."""

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry

    def export_all(self, filepath: Path) -> None:
        """Export all configuration (general + per-script) to a single YAML file."""
        payload: dict[str, Any] = {}

        cfg_path = config_file_path()
        if cfg_path.exists():
            try:
                loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload["general"] = loaded
            except Exception as exc:
                logger.warning("Failed to read config for export: %s", exc)

        if self._registry is not None:
            script_configs = self._registry.save_configs()
            if script_configs:
                payload["scripts"] = script_configs

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info("Exported all config to %s", filepath)

    def import_all(self, filepath: Path) -> dict[str, Any]:
        """Import configuration from a YAML file.

        Returns the parsed payload dict for the caller to apply.
        """
        if not filepath.exists():
            raise FileNotFoundError(f"Import file not found: {filepath}")

        raw = filepath.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError("Import file must contain a YAML mapping.")

        result: dict[str, Any] = {}
        general = loaded.get("general")
        if isinstance(general, dict):
            result["general"] = general

        scripts = loaded.get("scripts")
        if isinstance(scripts, dict):
            result["scripts"] = scripts

        return result

    def export_script(self, script_name: str, filepath: Path) -> None:
        """Export a single script's configuration to a YAML file."""
        if self._registry is None:
            raise RuntimeError("No script registry available")

        entry = self._registry.get(script_name)
        if entry is None:
            raise ValueError(f"Script not found: {script_name}")

        config = entry.script.save_config()
        config["enabled"] = entry.enabled
        config["__script_name__"] = script_name

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info("Exported script %s config to %s", script_name, filepath)

    def import_script(self, filepath: Path) -> tuple[str, dict[str, Any]]:
        """Import a single script's configuration from a YAML file.

        Returns (script_name, config_dict).
        """
        raw = filepath.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw)
        if loaded is None:
            raise ValueError("Import file is empty")
        if not isinstance(loaded, dict):
            raise ValueError("Import file must contain a YAML mapping")

        script_name = loaded.pop("__script_name__", filepath.stem)
        return script_name, loaded

    def migrate_to(self, new_dir: Path) -> Path:
        """Migrate all config files from the current config directory to a new one.

        Copies config.yaml, history.sqlite3, logs/, and any other files.
        Does NOT delete the original directory.
        Returns the new config directory path.
        """
        src_dir = get_config_dir()
        new_dir = new_dir.resolve()
        new_dir.mkdir(parents=True, exist_ok=True)

        for item in src_dir.iterdir():
            if item.is_file():
                shutil.copy2(item, new_dir / item.name)
            elif item.is_dir():
                dst = new_dir / item.name
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(item, dst)

        set_config_dir(new_dir)
        logger.info("Migrated config from %s to %s", src_dir, new_dir)
        return new_dir