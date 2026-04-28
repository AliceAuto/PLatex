from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from .script_base import ScriptBase
from .script_safety import (
    _MAX_SCRIPT_FILE_SIZE,
    _SCRIPT_SAFETY_ENV,
    _extract_legacy_result,
    _load_script_module,
    scan_script_source,
    validate_script_path,
)

logger = logging.getLogger("platex.registry")


@dataclass(slots=True)
class _LegacyOcrAdapter(ScriptBase):
    _module: ModuleType = field(repr=False)
    _source_path: Path = field(default_factory=Path)
    _context: Any = field(default=None, init=False, repr=False)
    _hotkeys_changed_callback: Any = field(default=None, init=False, repr=False)
    _tray_action_callback: Any = field(default=None, init=False, repr=False)

    @property
    def name(self) -> str:
        return self._source_path.stem

    @property
    def display_name(self) -> str:
        return self._source_path.stem.replace("_", " ").title()

    @property
    def description(self) -> str:
        doc = getattr(self._module, "__doc__", None)
        if doc and doc.strip():
            return doc.strip().split("\n")[0]
        return f"Legacy OCR script: {self._source_path.name}"

    def has_ocr_capability(self) -> bool:
        return True

    def process_image(self, image_bytes: bytes, context: dict[str, object] | None = None) -> str:
        process_image = getattr(self._module, "process_image", None)
        if not callable(process_image):
            raise RuntimeError(f"Script {self._source_path} does not define process_image(image_bytes, context)")

        result = process_image(image_bytes, context or {})
        return _extract_legacy_result(self._module, self._source_path, result)


@dataclass(slots=True)
class ScriptEntry:
    script: ScriptBase
    enabled: bool = True
    source_path: Path | None = None


class ScriptRegistry:

    def __init__(self) -> None:
        self._entries: dict[str, ScriptEntry] = {}
        self._scripts_dir: Path | None = None
        self._allowed_dirs: list[Path] = []

    @property
    def entries(self) -> dict[str, ScriptEntry]:
        return dict(self._entries)

    def get(self, name: str) -> ScriptEntry | None:
        return self._entries.get(name)

    def get_ocr_scripts(self) -> list[ScriptEntry]:
        return [e for e in self._entries.values() if e.enabled and e.script.has_ocr_capability()]

    def get_hotkey_scripts(self) -> list[ScriptEntry]:
        return [e for e in self._entries.values() if e.enabled and e.script.get_hotkey_bindings()]

    def get_enabled_scripts(self) -> list[ScriptEntry]:
        return [e for e in self._entries.values() if e.enabled]

    def clear(self) -> None:
        self._entries.clear()

    def get_all_scripts(self) -> list[ScriptEntry]:
        return list(self._entries.values())

    def discover_scripts(self, scripts_dir: Path) -> None:
        self._scripts_dir = scripts_dir
        resolved_dir = scripts_dir.resolve()
        if resolved_dir not in self._allowed_dirs:
            self._allowed_dirs.append(resolved_dir)
        if not scripts_dir.is_dir():
            logger.warning("Scripts directory does not exist: %s", scripts_dir)
            return

        for py_file in sorted(scripts_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                self._load_script_file(py_file)
            except Exception as exc:
                logger.exception("Failed to load script %s: %s", py_file, exc)

    def load_script_file(self, path: Path, enabled: bool = True) -> ScriptEntry | None:
        try:
            entry = self._load_script_file(path)
        except Exception as exc:
            logger.exception("Failed to load script %s: %s", path, exc)
            return None
        if entry is not None:
            entry.enabled = enabled
        return entry

    def _load_script_file(self, path: Path) -> ScriptEntry | None:
        validate_script_path(path)

        resolved = path.resolve()
        logger.info("Loading script from %s (size=%d)", resolved, resolved.stat().st_size)

        dangerous_warnings, blocked_warnings = scan_script_source(path)
        if blocked_warnings:
            logger.error(
                "Script %s contains BLOCKED patterns and cannot be loaded: %s. "
                "These patterns cannot be bypassed.",
                path, ", ".join(blocked_warnings),
            )
            raise ValueError(
                f"Script {path} contains blocked patterns: {', '.join(blocked_warnings)}. "
                f"These patterns cannot be bypassed."
            )
        if dangerous_warnings:
            allow_unsafe = os.environ.get(_SCRIPT_SAFETY_ENV, "").strip().lower() in ("1", "true", "yes")
            if allow_unsafe:
                logger.warning(
                    "Script %s contains potentially dangerous patterns: %s. "
                    "Loading allowed by %s environment variable.",
                    path, ", ".join(dangerous_warnings), _SCRIPT_SAFETY_ENV,
                )
            else:
                logger.error(
                    "Script %s contains dangerous patterns and is BLOCKED: %s. "
                    "Set %s=1 to allow loading at your own risk.",
                    path, ", ".join(dangerous_warnings), _SCRIPT_SAFETY_ENV,
                )
                raise ValueError(
                    f"Script {path} contains dangerous patterns: {', '.join(dangerous_warnings)}. "
                    f"Set {_SCRIPT_SAFETY_ENV}=1 to allow loading at your own risk."
                )

        module = _load_script_module(path)

        create_fn = getattr(module, "create_script", None)
        if callable(create_fn):
            script = create_fn()
            if isinstance(script, ScriptBase):
                if script.name in self._entries:
                    existing_path = self._entries[script.name].source_path
                    if existing_path is not None and existing_path.resolve() == resolved:
                        logger.info("Reloading script '%s' from %s", script.name, path)
                        entry = ScriptEntry(script=script, source_path=path)
                        self._entries[script.name] = entry
                        return entry
                    logger.warning(
                        "Script name '%s' from %s conflicts with already loaded script from %s; skipping",
                        script.name, path, existing_path,
                    )
                    return None
                entry = ScriptEntry(script=script, source_path=path)
                self._entries[script.name] = entry
                logger.info("Loaded new-style script: %s from %s", script.name, path)
                return entry

        process_image_fn = getattr(module, "process_image", None)
        if callable(process_image_fn):
            adapter = _LegacyOcrAdapter(_module=module, _source_path=path)
            if adapter.name in self._entries:
                existing_path = self._entries[adapter.name].source_path
                if existing_path is not None and existing_path.resolve() == resolved:
                    logger.info("Reloading legacy script '%s' from %s", adapter.name, path)
                    entry = ScriptEntry(script=adapter, source_path=path)
                    self._entries[adapter.name] = entry
                    return entry
                logger.warning(
                    "Script name '%s' from %s conflicts with already loaded script from %s; skipping",
                    adapter.name, path, existing_path,
                )
                return None
            entry = ScriptEntry(script=adapter, source_path=path)
            self._entries[adapter.name] = entry
            logger.info("Loaded legacy OCR script: %s from %s", adapter.name, path)
            return entry

        logger.warning("Script %s has neither create_script() nor process_image()", path)
        return None

    def load_configs(self, configs: dict[str, dict[str, Any]]) -> None:
        for name, entry in self._entries.items():
            script_config = configs.get(name, {})
            if not isinstance(script_config, dict):
                logger.warning("Invalid config for script %s: expected dict, got %s", name, type(script_config).__name__)
                script_config = {}
            entry.enabled = script_config.get("enabled", True)
            entry.script.load_config(script_config)

    def save_configs(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for name, entry in self._entries.items():
            config = entry.script.save_config()
            if not isinstance(config, dict):
                config = {}
            config["enabled"] = entry.enabled
            result[name] = config
        return result


def default_scripts_dir() -> Path:
    import sys

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "scripts")
        candidates.append(exe_dir / "_internal" / "scripts")
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / "scripts")
            candidates.append(Path(meipass) / "_internal" / "scripts")

    candidates.append(Path(__file__).resolve().parents[2] / "scripts")

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    logger.warning("Scripts directory not found in any candidate path. Tried: %s", candidates)
    return candidates[0]
