from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from .script_base import ScriptBase

logger = logging.getLogger("platex.registry")


@dataclass(slots=True)
class _LegacyOcrAdapter(ScriptBase):
    """Adapts a legacy script module (with module-level process_image) to ScriptBase."""

    _module: ModuleType = field(repr=False)
    _source_path: Path = field(default_factory=Path)

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
        if isinstance(result, str):
            latex = result
        elif isinstance(result, dict) and "latex" in result:
            latex = str(result["latex"])
        else:
            raise RuntimeError(f"Script {self._source_path} returned an unsupported result")

        latex = latex.strip()
        if not latex:
            raise RuntimeError(f"Script {self._source_path} returned empty LaTeX")
        return latex


@dataclass(slots=True)
class ScriptEntry:
    """A loaded script instance with its metadata."""

    script: ScriptBase
    enabled: bool = True
    source_path: Path | None = None


class ScriptRegistry:
    """Discovers, loads, and manages script instances."""

    def __init__(self) -> None:
        self._entries: dict[str, ScriptEntry] = {}
        self._scripts_dir: Path | None = None

    @property
    def entries(self) -> dict[str, ScriptEntry]:
        return dict(self._entries)

    def get(self, name: str) -> ScriptEntry | None:
        return self._entries.get(name)

    def get_ocr_scripts(self) -> list[ScriptEntry]:
        """Return all enabled scripts that have OCR capability."""
        return [e for e in self._entries.values() if e.enabled and e.script.has_ocr_capability()]

    def get_hotkey_scripts(self) -> list[ScriptEntry]:
        """Return all enabled scripts that have hotkey bindings."""
        return [e for e in self._entries.values() if e.enabled and e.script.get_hotkey_bindings()]

    def get_enabled_scripts(self) -> list[ScriptEntry]:
        """Return all enabled scripts."""
        return [e for e in self._entries.values() if e.enabled]

    def get_all_scripts(self) -> list[ScriptEntry]:
        return list(self._entries.values())

    def discover_scripts(self, scripts_dir: Path) -> None:
        """Scan a directory for script files and load them."""
        self._scripts_dir = scripts_dir
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
        """Load a single script file and register it."""
        entry = self._load_script_file(path)
        if entry is not None:
            entry.enabled = enabled
        return entry

    def _load_script_file(self, path: Path) -> ScriptEntry | None:
        """Load a script file. Tries new-style (create_script) first, then legacy (process_image)."""
        module_name = f"platex_script_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.error("Cannot create module spec for %s", path)
            return None

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Try new-style: module has create_script() -> ScriptBase
        create_fn = getattr(module, "create_script", None)
        if callable(create_fn):
            script = create_fn()
            if isinstance(script, ScriptBase):
                entry = ScriptEntry(script=script, source_path=path)
                self._entries[script.name] = entry
                logger.info("Loaded new-style script: %s from %s", script.name, path)
                return entry

        # Try legacy: module has process_image() function
        process_image_fn = getattr(module, "process_image", None)
        if callable(process_image_fn):
            adapter = _LegacyOcrAdapter(_module=module, _source_path=path)
            entry = ScriptEntry(script=adapter, source_path=path)
            self._entries[adapter.name] = entry
            logger.info("Loaded legacy OCR script: %s from %s", adapter.name, path)
            return entry

        logger.warning("Script %s has neither create_script() nor process_image()", path)
        return None

    def load_configs(self, configs: dict[str, dict[str, Any]]) -> None:
        """Load configuration for each registered script.

        configs is a dict of {script_name: config_dict}.
        """
        for name, entry in self._entries.items():
            script_config = configs.get(name, {})
            entry.enabled = script_config.get("enabled", True)
            entry.script.load_config(script_config)

    def save_configs(self) -> dict[str, dict[str, Any]]:
        """Collect configs from all scripts and return as {script_name: config_dict}."""
        result: dict[str, dict[str, Any]] = {}
        for name, entry in self._entries.items():
            config = entry.script.save_config()
            config["enabled"] = entry.enabled
            result[name] = config
        return result


def default_scripts_dir() -> Path:
    """Return the default scripts directory."""
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