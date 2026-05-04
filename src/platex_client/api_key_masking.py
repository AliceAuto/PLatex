from __future__ import annotations

import copy
import os
import re
from typing import Any


_SENSITIVE_KEY_SUFFIXES = ("api_key", "secret", "token", "password", "apikey")

_SENSITIVE_KEY_PATTERN = r'[a-zA-Z_]*(?:api_key|apikey|secret|token|password)'


def is_sensitive_key(key: str) -> bool:
    key_lower = key.lower()
    return any(key_lower.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


def strip_api_keys(data: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(data)

    def _strip(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if is_sensitive_key(k) and isinstance(v, str) and v:
                    obj[k] = "********"
                else:
                    _strip(v)
        elif isinstance(obj, list):
            for item in obj:
                _strip(item)

    _strip(result)
    return result


def hide_api_key(yaml_text: str) -> str:
    return re.sub(
        rf'^(\s*{_SENSITIVE_KEY_PATTERN}\s*:\s*).*$',
        r'\1***',
        yaml_text,
        flags=re.MULTILINE,
    )


def _is_masked_value(val: str) -> bool:
    if val.startswith("*"):
        return True
    if re.match(r"^.{1,4}\*+$", val):
        return True
    return False


def restore_api_key(edited_text: str, original_text: str) -> str:
    edited_lines = edited_text.split("\n")
    original_lines = original_text.split("\n")
    result_lines: list[str] = []

    def _path_for_line(line: str) -> str:
        m = re.match(rf'^(\s*)({_SENSITIVE_KEY_PATTERN})\s*:', line)
        if not m:
            return ""
        indent = len(m.group(1))
        key = m.group(2)
        return f"{indent}:{key}"

    orig_key_values: dict[str, list[str]] = {}
    for line in original_lines:
        path = _path_for_line(line)
        if path:
            m = re.match(rf'^\s*{_SENSITIVE_KEY_PATTERN}\s*:\s*(.+)$', line)
            if m:
                val = m.group(1).strip()
                orig_key_values.setdefault(path, []).append(val)

    orig_key_cursors: dict[str, int] = {}
    for line in edited_lines:
        path = _path_for_line(line)
        if path and path in orig_key_values:
            m = re.match(rf'^(\s*{_SENSITIVE_KEY_PATTERN}\s*:\s*)(.+)$', line)
            if m:
                prefix = m.group(1)
                val = m.group(2).strip()
                if _is_masked_value(val):
                    idx = orig_key_cursors.get(path, 0)
                    values = orig_key_values[path]
                    if idx < len(values):
                        result_lines.append(prefix + values[idx])
                        orig_key_cursors[path] = idx + 1
                        continue
        result_lines.append(line)
    result = "\n".join(result_lines)
    if original_text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


def fill_masked_api_keys(data: dict[str, Any], real_values: dict[str, Any] | None = None) -> dict[str, Any]:
    result = copy.deepcopy(data)
    if real_values is None:
        return result

    def _is_masked(val: Any) -> bool:
        if not isinstance(val, str):
            return False
        return val.startswith("*") or bool(re.match(r"^.{1,4}\*+$", val))

    def _fill(obj: Any, ref: Any) -> None:
        if isinstance(obj, dict) and isinstance(ref, dict):
            keys_to_remove: list[str] = []
            for k in obj:
                if k in ref:
                    if _is_masked(obj[k]):
                        if _is_masked(ref[k]):
                            keys_to_remove.append(k)
                        else:
                            obj[k] = copy.deepcopy(ref[k])
                    elif _is_masked(ref[k]) and not _is_masked(obj[k]):
                        pass
                    else:
                        _fill(obj[k], ref[k])
                elif _is_masked(obj[k]):
                    keys_to_remove.append(k)
            for k in keys_to_remove:
                del obj[k]

    _fill(result, real_values)
    return result
