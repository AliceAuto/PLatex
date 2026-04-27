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
    orig_key_values: dict[str, list[str]] = {}
    for line in original_lines:
        m = re.match(rf'^\s*({_SENSITIVE_KEY_PATTERN})\s*:\s*(.+)$', line)
        if m:
            key_name = m.group(1)
            val = m.group(2).strip()
            orig_key_values.setdefault(key_name, []).append(val)

    orig_key_cursors: dict[str, int] = {}
    for line in edited_lines:
        m = re.match(rf'^(\s*{_SENSITIVE_KEY_PATTERN}\s*:\s*)(.+)$', line)
        if m:
            prefix = m.group(1)
            val = m.group(2).strip()
            key_name_match = re.match(rf'^\s*({_SENSITIVE_KEY_PATTERN})', prefix.strip())
            key_name_str = key_name_match.group(1) if key_name_match else "api_key"
            if _is_masked_value(val) and key_name_str in orig_key_values:
                idx = orig_key_cursors.get(key_name_str, 0)
                values = orig_key_values[key_name_str]
                if idx < len(values):
                    result_lines.append(prefix + values[idx])
                    orig_key_cursors[key_name_str] = idx + 1
                else:
                    result_lines.append(line)
            else:
                result_lines.append(line)
        else:
            result_lines.append(line)
    result = "\n".join(result_lines)
    if original_text.endswith("\n") and not result.endswith("\n"):
        result += "\n"
    return result


def fill_masked_api_keys(data: dict[str, Any]) -> dict[str, Any]:
    from .secrets import get_secret
    env_key = get_secret("GLM_API_KEY", os.getenv("GLM_API_KEY", ""))
    data = dict(data)
    if isinstance(data.get("glm_api_key"), str):
        val = data["glm_api_key"]
        if _is_masked_value(val):
            if env_key:
                data["glm_api_key"] = env_key
    scripts = data.get("scripts")
    if isinstance(scripts, dict):
        new_scripts = {}
        for name, cfg in scripts.items():
            if isinstance(cfg, dict):
                new_cfg = dict(cfg)
                ak = new_cfg.get("api_key", "")
                if isinstance(ak, str) and _is_masked_value(ak):
                    script_env = get_secret(f"PLATEX_API_KEY_{name.upper()}", os.getenv(f"PLATEX_API_KEY_{name.upper()}", env_key))
                    if script_env:
                        new_cfg["api_key"] = script_env
                new_scripts[name] = new_cfg
            else:
                new_scripts[name] = cfg
        data["scripts"] = new_scripts
    return data
