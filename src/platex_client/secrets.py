from __future__ import annotations

import threading
from typing import Any

_lock = threading.Lock()
_secrets: dict[str, list[str]] = []


def _find_secret_index(key: str) -> int:
    for i, entry in enumerate(_secrets):
        if entry[0] == key:
            return i
    return -1


def set_secret(key: str, value: str) -> None:
    with _lock:
        idx = _find_secret_index(key)
        if idx >= 0:
            old = _secrets[idx][1]
            try:
                buf = bytearray(old.encode("utf-8"))
                for j in range(len(buf)):
                    buf[j] = 0
            except Exception:
                pass
            _secrets[idx][1] = value
        else:
            _secrets.append([key, value])


def get_secret(key: str, default: str = "") -> str:
    with _lock:
        idx = _find_secret_index(key)
        if idx >= 0:
            return _secrets[idx][1]
        return default


def has_secret(key: str) -> bool:
    with _lock:
        return _find_secret_index(key) >= 0


def delete_secret(key: str) -> None:
    with _lock:
        idx = _find_secret_index(key)
        if idx >= 0:
            old = _secrets[idx][1]
            try:
                buf = bytearray(old.encode("utf-8"))
                for j in range(len(buf)):
                    buf[j] = 0
            except Exception:
                pass
            _secrets.pop(idx)


def clear_all() -> None:
    with _lock:
        for entry in _secrets:
            try:
                buf = bytearray(entry[1].encode("utf-8"))
                for j in range(len(buf)):
                    buf[j] = 0
            except Exception:
                pass
        _secrets.clear()


def get_all_keys() -> list[str]:
    with _lock:
        return [entry[0] for entry in _secrets]
