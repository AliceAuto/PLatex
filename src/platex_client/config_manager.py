from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("platex.config_manager")

_REGISTRY_KEY = r"Software\PLatexClient"
_REGISTRY_VALUE = "ConfigDir"

_MAX_BACKUPS = 10


def _default_config_dir() -> Path:
    from platformdirs import user_config_dir
    return Path(user_config_dir("PLatexClient", "Copilot"))


def get_config_dir() -> Path:
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
    return get_config_dir() / "config.yaml"


def db_file_path() -> Path:
    return get_config_dir() / "history.sqlite3"


def log_file_path() -> Path:
    return get_config_dir() / "logs" / "platex-client.log"


def backups_dir() -> Path:
    return get_config_dir() / "backups"


def _current_config_version() -> int:
    from . import __config_version__
    return __config_version__


def _read_config_version(cfg_path: Path) -> int:
    if not cfg_path.exists():
        return 0
    try:
        raw = cfg_path.read_text(encoding="utf-8")
        payload = yaml.safe_load(raw)
        if isinstance(payload, dict):
            return int(payload.get("config_version", 1))
    except Exception as exc:
        logger.warning("Failed to read config version from %s: %s", cfg_path, exc)
    return 1


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def backup_config() -> Path | None:
    cfg_dir = get_config_dir()
    cfg_path = cfg_dir / "config.yaml"

    if not cfg_path.exists():
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    bk_dir = backups_dir()
    bk_dir.mkdir(parents=True, exist_ok=True)

    dest_dir = bk_dir / timestamp
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        shutil.copy2(cfg_path, dest_dir / "config.yaml")
    except Exception as exc:
        logger.error("Failed to backup config.yaml: %s", exc)
        return None

    scripts_dir = cfg_dir / "scripts"
    if scripts_dir.is_dir():
        try:
            dest_scripts = dest_dir / "scripts"
            shutil.copytree(scripts_dir, dest_scripts, ignore=_skip_symlinks)
        except Exception as exc:
            logger.warning("Failed to backup scripts config: %s", exc)

    _cleanup_old_backups()

    logger.info("Config backed up to %s", dest_dir)
    return dest_dir


def _cleanup_old_backups() -> None:
    bk_dir = backups_dir()
    if not bk_dir.is_dir():
        return

    try:
        entries = sorted(
            [d for d in bk_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
    except Exception:
        return

    for old in entries[_MAX_BACKUPS:]:
        try:
            shutil.rmtree(old)
            logger.debug("Removed old backup: %s", old)
        except Exception as exc:
            logger.warning("Failed to remove old backup %s: %s", old, exc)


def migrate_config() -> None:
    cfg_path = config_file_path()
    if not cfg_path.exists():
        return

    current_version = _current_config_version()
    file_version = _read_config_version(cfg_path)

    if file_version >= current_version:
        return

    logger.info("Config migration needed: file version %d -> current version %d", file_version, current_version)

    backup_config()

    try:
        raw = cfg_path.read_text(encoding="utf-8")
        payload = yaml.safe_load(raw)
    except Exception as exc:
        logger.error("Failed to read config for migration: %s", exc)
        return

    if not isinstance(payload, dict):
        logger.error("Config file is not a mapping, skipping migration")
        return

    migrated = _apply_migrations(payload, file_version, current_version)
    migrated["config_version"] = current_version

    try:
        cfg_path.write_text(
            yaml.safe_dump(migrated, sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info("Config migrated from version %d to %d", file_version, current_version)
    except Exception as exc:
        logger.error("Failed to write migrated config: %s", exc)


def _apply_migrations(payload: dict[str, Any], from_version: int, to_version: int) -> dict[str, Any]:
    result = dict(payload)

    if from_version < 2:
        result.setdefault("ui_language", "en")
        result.setdefault("language_pack", "")
        result.setdefault("auto_start", False)
        if "scripts" not in result or not isinstance(result.get("scripts"), dict):
            result["scripts"] = {}
        scripts = result["scripts"]
        if "glm_vision_ocr" not in scripts:
            scripts["glm_vision_ocr"] = {
                "model": result.get("glm_model", "glm-4.1v-thinking-flash"),
                "base_url": result.get("glm_base_url", "https://open.bigmodel.cn/api/paas/v4/chat/completions"),
                "enabled": True,
            }
        if "hotkey_click" not in scripts:
            scripts["hotkey_click"] = {"enabled": True, "entries": []}

    return result


_MAX_IMPORT_FILE_SIZE = 1 * 1024 * 1024
_ALLOWED_GENERAL_KEYS = {
    "db_path", "script", "log_file", "interval", "isolate_mode",
    "glm_api_key", "glm_model", "glm_base_url", "auto_start",
    "ui_language", "language_pack",
}


class ConfigManager:
    """High-level config export/import manager."""

    def __init__(self, registry: Any | None = None) -> None:
        self._registry = registry

    def export_all(self, filepath: Path) -> None:
        from .api_key_masking import strip_api_keys
        payload: dict[str, Any] = {}

        cfg_path = config_file_path()
        if cfg_path.exists():
            try:
                loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    payload["general"] = strip_api_keys(loaded)
            except Exception as exc:
                logger.warning("Failed to read config for export: %s", exc)

        if self._registry is not None:
            script_configs = self._registry.save_configs()
            if script_configs:
                payload["scripts"] = strip_api_keys(script_configs)

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

        if filepath.is_symlink():
            raise ValueError(f"Import file is a symlink (not allowed): {filepath}")

        file_size = filepath.stat().st_size
        if file_size > _MAX_IMPORT_FILE_SIZE:
            raise ValueError(
                f"Import file too large ({file_size} bytes, max {_MAX_IMPORT_FILE_SIZE}): {filepath}"
            )

        raw = filepath.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw)
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise ValueError("Import file must contain a YAML mapping.")

        result: dict[str, Any] = {}
        general = loaded.get("general")
        if isinstance(general, dict):
            filtered_general = {k: v for k, v in general.items() if k in _ALLOWED_GENERAL_KEYS}
            if len(filtered_general) < len(general):
                rejected = set(general.keys()) - _ALLOWED_GENERAL_KEYS
                logger.warning("Import general section had unknown keys rejected: %s", rejected)
            result["general"] = filtered_general

        scripts = loaded.get("scripts")
        if isinstance(scripts, dict):
            result["scripts"] = scripts

        return result

    def export_script(self, script_name: str, filepath: Path) -> None:
        from .api_key_masking import strip_api_keys
        if self._registry is None:
            raise RuntimeError("No script registry available")

        entry = self._registry.get(script_name)
        if entry is None:
            raise ValueError(f"Script not found: {script_name}")

        config = entry.script.save_config()
        config["enabled"] = entry.enabled
        config["__script_name__"] = script_name
        config = strip_api_keys(config)

        filepath.parent.mkdir(parents=True, exist_ok=True)
        filepath.write_text(
            yaml.safe_dump(config, sort_keys=False, allow_unicode=True, default_flow_style=False),
            encoding="utf-8",
        )
        logger.info("Exported script %s config to %s", script_name, filepath)

    def import_script(self, filepath: Path) -> tuple[str, dict[str, Any]]:
        if not filepath.exists():
            raise FileNotFoundError(f"Import file not found: {filepath}")

        if filepath.is_symlink():
            raise ValueError(f"Import file is a symlink (not allowed): {filepath}")

        file_size = filepath.stat().st_size
        if file_size > _MAX_IMPORT_FILE_SIZE:
            raise ValueError(f"Import file too large ({file_size} bytes, max {_MAX_IMPORT_FILE_SIZE})")

        raw = filepath.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw)
        if loaded is None:
            raise ValueError("Import file is empty")
        if not isinstance(loaded, dict):
            raise ValueError("Import file must contain a YAML mapping")

        script_name = loaded.pop("__script_name__", filepath.stem)
        if not isinstance(script_name, str) or not script_name.isidentifier():
            raise ValueError(f"Invalid script name in import file: {script_name!r}")

        return script_name, loaded

    def migrate_to(self, new_dir: Path) -> Path:
        src_dir = get_config_dir()
        new_dir = new_dir.resolve()
        new_dir.mkdir(parents=True, exist_ok=True)

        deep_symlinks = _has_deep_symlinks(src_dir)
        if deep_symlinks:
            logger.warning(
                "Source directory contains %d symlink(s) that will be skipped during migration: %s",
                len(deep_symlinks),
                ", ".join(str(p) for p in deep_symlinks[:10]),
            )

        lock_path = src_dir / ".migration.lock"
        lock_fd = None
        try:
            if os.name == "nt":
                import msvcrt
                lock_fd = open(lock_path, "w")
                msvcrt.lockf(lock_fd, msvcrt.LK_NBLCK, 1)

            for item in src_dir.iterdir():
                if item.name == ".migration.lock":
                    continue
                if item.is_symlink():
                    logger.warning("Skipping symlink during migration: %s -> %s", item, item.resolve())
                    continue
                if item.is_file():
                    shutil.copy2(item, new_dir / item.name)
                elif item.is_dir():
                    dst = new_dir / item.name
                    if dst.exists():
                        if dst.is_symlink():
                            logger.warning("Skipping symlink during migration: %s", dst)
                            continue
                        shutil.rmtree(dst)
                    shutil.copytree(item, dst, ignore=_skip_symlinks)
        finally:
            if lock_fd is not None:
                try:
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.lockf(lock_fd, msvcrt.LK_UNLCK, 1)
                    lock_fd.close()
                except Exception:
                    pass
            try:
                lock_path.unlink(missing_ok=True)
            except Exception:
                pass

        set_config_dir(new_dir)
        logger.info("Migrated config from %s to %s", src_dir, new_dir)
        return new_dir


def _skip_symlinks(directory: str, contents: list[str]) -> list[str]:
    """Return names of symlinks to skip during copytree."""
    skipped: list[str] = []
    base = Path(directory)
    for name in contents:
        item = base / name
        if item.is_symlink():
            logger.warning("Skipping symlink during migration: %s", item)
            skipped.append(name)
    return skipped


def _has_deep_symlinks(directory: Path) -> list[Path]:
    """Walk directory tree and return all symlink paths found."""
    symlinks: list[Path] = []
    try:
        for root, dirs, files in os.walk(directory, followlinks=False):
            root_path = Path(root)
            for name in files + dirs:
                item = root_path / name
                if item.is_symlink():
                    symlinks.append(item)
    except Exception:
        pass
    return symlinks
