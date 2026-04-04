from __future__ import annotations

import argparse
import time
from pathlib import Path

from .clipboard import copy_text_to_clipboard
from .history import HistoryStore
from .loader import load_script_processor
from .watcher import ClipboardWatcher


def _default_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "scripts" / "glm_vision_ocr.py"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platex-client", description="Clipboard watcher for OCR to LaTeX.")
    parser.add_argument("--db-path", type=Path, default=None, help="Optional SQLite database path.")
    parser.add_argument("--script", type=Path, default=_default_script_path(), help="OCR script to mount.")
    parser.add_argument("--interval", type=float, default=0.8, help="Polling interval in seconds.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="Start clipboard monitoring.")

    history_parser = subparsers.add_parser("history", help="Show recent OCR history.")
    history_parser.add_argument("--limit", type=int, default=10)

    subparsers.add_parser("latest", help="Show the latest OCR result.")
    subparsers.add_parser("copy-latest", help="Copy the latest OCR result to the clipboard.")
    return parser


def _print_event(prefix: str, event) -> None:
    if event.status == "ok":
        print(f"{prefix} {event.image_hash[:10]} {event.image_width}x{event.image_height}")
        print(event.latex)
    else:
        print(f"{prefix} {event.image_hash[:10]} failed: {event.error}")


def _serve(args: argparse.Namespace) -> int:
    history = HistoryStore(args.db_path)
    processor = load_script_processor(args.script)
    watcher = ClipboardWatcher(processor=processor, history=history, source_name=str(args.script))

    print(f"Watching clipboard. Mounted script: {args.script}")
    try:
        while True:
            event = watcher.poll_once()
            if event is not None:
                _print_event("Captured", event)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def _print_history(history: HistoryStore, limit: int) -> int:
    records = history.list_recent(limit=limit)
    if not records:
        print("No history yet.")
        return 0

    for index, record in enumerate(records, start=1):
        if record.status == "ok":
            print(f"{index}. {record.created_at.isoformat()} {record.image_hash[:10]} {record.image_width}x{record.image_height}")
            print(record.latex)
        else:
            print(f"{index}. {record.created_at.isoformat()} {record.image_hash[:10]} error: {record.error}")
    return 0


def _print_latest(history: HistoryStore) -> int:
    record = history.latest()
    if record is None:
        print("No history yet.")
        return 0

    _print_event("Latest", record)
    return 0


def _copy_latest(history: HistoryStore) -> int:
    record = history.latest()
    if record is None or record.status != "ok" or not record.latex.strip():
        print("No successful OCR result to copy.")
        return 1

    copy_text_to_clipboard(record.latex)
    print("Copied latest LaTeX result to clipboard.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    history = HistoryStore(args.db_path)

    if args.command == "serve":
        return _serve(args)
    if args.command == "history":
        return _print_history(history, args.limit)
    if args.command == "latest":
        return _print_latest(history)
    if args.command == "copy-latest":
        return _copy_latest(history)

    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())