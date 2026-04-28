from __future__ import annotations

import logging
import re
from pathlib import Path

from rich.logging import RichHandler

_SENSITIVE_PATTERNS = [
    (re.compile(r'(api[_-]?key\s*[:=]\s*)\S+', re.IGNORECASE), r'\1***'),
    (re.compile(r'(token\s*[:=]\s*)\S+', re.IGNORECASE), r'\1***'),
    (re.compile(r'(secret\s*[:=]\s*)\S+', re.IGNORECASE), r'\1***'),
    (re.compile(r'(password\s*[:=]\s*)\S+', re.IGNORECASE), r'\1***'),
]


class _SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            masked_msg = record.msg
            for pattern, replacement in _SENSITIVE_PATTERNS:
                masked_msg = pattern.sub(replacement, masked_msg)
            if masked_msg != record.msg:
                record.msg = masked_msg
        if record.args and isinstance(record.args, tuple):
            new_args = []
            changed = False
            for arg in record.args:
                if isinstance(arg, str):
                    masked_arg = arg
                    for pattern, replacement in _SENSITIVE_PATTERNS:
                        masked_arg = pattern.sub(replacement, masked_arg)
                    if masked_arg != arg:
                        changed = True
                    new_args.append(masked_arg)
                else:
                    new_args.append(arg)
            if changed:
                record.args = tuple(new_args)
        return True


def setup_logging(log_file: Path, *, level: int = logging.INFO) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()

    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    existing_file_handler = None
    for handler in list(root_logger.handlers):
        if isinstance(handler, logging.FileHandler):
            existing_file_handler = handler
            break

    if existing_file_handler is not None:
        try:
            current_path = Path(existing_file_handler.baseFilename).resolve()
        except Exception:
            current_path = None
        if current_path == log_file.resolve():
            existing_file_handler.setFormatter(file_formatter)
            return
        root_logger.removeHandler(existing_file_handler)
        existing_file_handler.close()

    has_sensitive_filter = any(
        isinstance(f, _SensitiveDataFilter) for f in root_logger.filters
    )
    if not has_sensitive_filter:
        root_logger.setLevel(level)
        root_logger.addFilter(_SensitiveDataFilter())

    has_console_handler = any(
        isinstance(h, RichHandler) for h in root_logger.handlers
    )
    if not has_console_handler:
        console_handler = RichHandler(
            show_time=True,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
        )
        root_logger.addHandler(console_handler)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)
