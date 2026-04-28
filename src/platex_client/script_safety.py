from __future__ import annotations

import importlib.util
import logging
import os
import re
from pathlib import Path
from types import ModuleType

_DANGEROUS_PATTERNS = [
    (re.compile(r'\bos\.system\b'), 'os.system'),
    (re.compile(r'\bsubprocess\.(call|run|Popen|check_output|check_call)\b'), 'subprocess execution'),
    (re.compile(r'\bexec\s*\('), 'exec()'),
    (re.compile(r'\beval\s*\('), 'eval()'),
    (re.compile(r'\b__import__\s*\('), '__import__()'),
    (re.compile(r'\bshutil\.rmtree\b'), 'shutil.rmtree'),
    (re.compile(r'\bos\.remove\b'), 'os.remove'),
    (re.compile(r'(?<!\.)\bcompile\s*\('), 'compile()'),
    (re.compile(r'\b__builtins__\b'), '__builtins__ access'),
    (re.compile(r'\bimportlib\.import_module\b'), 'importlib.import_module()'),
    (re.compile(r'\bgetattr\s*\(\s*\w+\s*,\s*["\'](?:system|popen|exec|eval|__import__|spawn)\b'), 'getattr() obfuscated call'),
    (re.compile(r'\bos\.popen\b'), 'os.popen()'),
    (re.compile(r'\bos\.spawn\w*\b'), 'os.spawn*()'),
    (re.compile(r'\bctypes\.(windll|cdll|oledll|pydll|CDLL|WinDLL)\b'), 'ctypes FFI access'),
    (re.compile(r'\bctypes\.CFUNCTYPE\b'), 'ctypes callback'),
    (re.compile(r'\bsocket\.socket\b'), 'socket access'),
    (re.compile(r'\bwebbrowser\.\w+\b'), 'webbrowser access'),
    (re.compile(r'\bopen\s*\(\s*["\']\w'), 'file open() with path literal'),
    (re.compile(r'\bshutil\.copy\w*\b'), 'shutil.copy*()'),
    (re.compile(r'\bos\.rename\b'), 'os.rename()'),
    (re.compile(r'\bos\.unlink\b'), 'os.unlink()'),
    (re.compile(r'\bos\.rmdir\b'), 'os.rmdir()'),
    (re.compile(r'\bos\.mkdir\b'), 'os.mkdir()'),
    (re.compile(r'\bos\.makedirs\b'), 'os.makedirs()'),
    (re.compile(r'\bpickle\.loads?\b'), 'pickle deserialization'),
    (re.compile(r'\bmarshal\.loads?\b'), 'marshal deserialization'),
    (re.compile(r'\bshelve\.\w+\b'), 'shelve access'),
    (re.compile(r'\btempfile\.\w+\b'), 'tempfile access'),
    (re.compile(r'\brequests\.(get|post|put|delete|patch|head|options)\b'), 'requests HTTP call'),
    (re.compile(r'\bos\.environ\b'), 'os.environ access'),
    (re.compile(r'\bopen\s*\(\s*["\']w'), 'file write'),
    (re.compile(r'\bPath\s*\(\s*.*\)\s*\.write_text\b'), 'Path.write_text'),
    (re.compile(r'\bPath\s*\(\s*.*\)\s*\.write_bytes\b'), 'Path.write_bytes'),
    (re.compile(r'\bos\.replace\b'), 'os.replace()'),
    (re.compile(r'\bimportlib\b'), 'importlib (dynamic import)'),
]

_BLOCKED_PATTERNS = [
    (re.compile(r'\bos\.system\b'), 'os.system'),
    (re.compile(r'\bsubprocess\.(call|run|Popen|check_output|check_call)\b'), 'subprocess execution'),
    (re.compile(r'\bexec\s*\('), 'exec()'),
    (re.compile(r'\beval\s*\('), 'eval()'),
    (re.compile(r'\b__import__\s*\('), '__import__()'),
    (re.compile(r'(?<!\.)\bcompile\s*\('), 'compile()'),
    (re.compile(r'\b__builtins__\b'), '__builtins__ access'),
    (re.compile(r'\bpickle\.loads?\b'), 'pickle deserialization'),
    (re.compile(r'\bmarshal\.loads?\b'), 'marshal deserialization'),
    (re.compile(r'\bos\.popen\b'), 'os.popen()'),
]

_MAX_SCRIPT_FILE_SIZE = 1 * 1024 * 1024

_SCRIPT_SAFETY_ENV = 'PLATEX_ALLOW_UNSAFE_SCRIPTS'

logger = logging.getLogger("platex.script_safety")


def scan_script_source(path: Path) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    blocked: list[str] = []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return warnings, blocked

    for pattern, label in _DANGEROUS_PATTERNS:
        if pattern.search(source):
            warnings.append(label)

    for pattern, label in _BLOCKED_PATTERNS:
        if pattern.search(source):
            blocked.append(label)

    return warnings, blocked


def check_blocked_patterns(path: Path) -> list[str]:
    blocked: list[str] = []
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return blocked

    for pattern, label in _BLOCKED_PATTERNS:
        if pattern.search(source):
            blocked.append(label)

    return blocked


def _check_dangerous_patterns(path: Path) -> None:
    warnings, blocked = scan_script_source(path)

    if blocked:
        allow_unsafe = os.getenv(_SCRIPT_SAFETY_ENV, "").strip().lower() in ("1", "true", "yes")
        if not allow_unsafe:
            logger.error(
                "Script %s contains BLOCKED patterns (%s) and is BLOCKED. "
                "Set environment variable %s=1 to allow loading unsafe scripts.",
                path, ", ".join(blocked), _SCRIPT_SAFETY_ENV,
            )
            raise ValueError(
                f"Script {path} contains blocked dangerous patterns: {', '.join(blocked)}. "
                f"Set {_SCRIPT_SAFETY_ENV}=1 to override at your own risk."
            )
        logger.warning(
            "Script %s contains BLOCKED patterns: %s. "
            "Loading anyway because %s is set. This is a security risk.",
            path, ", ".join(blocked), _SCRIPT_SAFETY_ENV,
        )
    elif warnings:
        logger.warning(
            "Script %s contains potentially dangerous patterns: %s. "
            "Exercise caution when running scripts from untrusted sources.",
            path, ", ".join(warnings),
        )


def validate_script_path(script_path: Path) -> None:
    if not script_path.exists():
        raise FileNotFoundError(f"OCR script not found: {script_path}")

    resolved = script_path.resolve()

    if script_path.is_symlink():
        raise ValueError(f"Script path is a symlink (not allowed): {script_path} -> {resolved}")

    if ".." in script_path.parts:
        raise ValueError(f"Script path contains '..' segments (not allowed): {script_path}")

    if not resolved.is_file():
        raise ValueError(f"Script path is not a regular file: {resolved}")

    try:
        if os.path.samefile(str(script_path), str(resolved)) and script_path != resolved:
            raise ValueError(f"Script path resolves to a different location (possible symlink attack): {script_path} -> {resolved}")
    except OSError:
        pass

    file_size = resolved.stat().st_size
    if file_size > _MAX_SCRIPT_FILE_SIZE:
        raise ValueError(
            f"Script file too large ({file_size} bytes, max {_MAX_SCRIPT_FILE_SIZE}): {resolved}"
        )

    if file_size == 0:
        raise ValueError(f"Script file is empty: {resolved}")


def _load_script_module(script_path: Path) -> ModuleType:
    resolved = script_path.resolve()
    module_name = f"platex_script_{script_path.stem}_{hash(str(resolved)) & 0xFFFFFFFF:x}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load script from {script_path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise RuntimeError(f"Failed to execute script {script_path}: {exc}") from exc

    return module


def _extract_legacy_result(module: ModuleType, script_path: Path, result: object) -> str:
    if isinstance(result, str):
        latex = result
    elif isinstance(result, dict) and "latex" in result:
        latex = str(result["latex"])
    else:
        raise RuntimeError(f"Script {script_path} returned an unsupported result")

    latex = latex.strip()
    if not latex:
        raise RuntimeError(f"Script {script_path} returned empty LaTeX")
    return latex
