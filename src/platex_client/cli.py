from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from platformdirs import user_data_dir

if sys.platform == "win32":
    import msvcrt


_INSTANCE_LOCK_HANDLE = None

if __package__ in {None, ""}:
    if getattr(sys, "frozen", False):
        frozen_root = Path(getattr(sys, "_MEIPASS", Path.cwd()))
        if str(frozen_root) not in sys.path:
            sys.path.insert(0, str(frozen_root))
    package_root = Path(__file__).resolve().parent.parent
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    __package__ = "platex_client"

from .app import PlatexApp
from .clipboard import copy_text_to_clipboard
from .config import default_config_path, default_log_path, load_config
from .history import HistoryStore
from .loader import load_script_processor
from .logging_utils import setup_logging
from .tray import TrayController
from .watcher import ClipboardWatcher
from .windows_clipboard import publish_text_to_clipboard


def _default_script_path() -> Path:
    script_name = Path("scripts") / "glm_vision_ocr.py"

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        # 1) Beside exe: release/PLatexClient-0.1.0/scripts/glm_vision_ocr.py
        candidates.append(Path(sys.executable).resolve().parent / script_name)
        # 2) PyInstaller temp extraction dir (when bundled with add-data)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / script_name)

    # 3) Source tree fallback for dev mode
    candidates.append(Path(__file__).resolve().parents[2] / script_name)

    for candidate in candidates:
        if candidate.exists():
            return candidate

    # Keep deterministic error path if nothing exists
    return candidates[0]


def _acquire_single_instance_lock() -> bool:
    global _INSTANCE_LOCK_HANDLE
    if sys.platform != "win32":
        return True

    lock_dir = Path(user_data_dir("PLatexClient", "Copilot"))
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_file = lock_dir / "platex-client.lock"

    handle = open(lock_file, "a+b")
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return False

    _INSTANCE_LOCK_HANDLE = handle
    return True


def _release_single_instance_lock() -> None:
    global _INSTANCE_LOCK_HANDLE
    if _INSTANCE_LOCK_HANDLE is None:
        return

    handle = _INSTANCE_LOCK_HANDLE
    _INSTANCE_LOCK_HANDLE = None
    try:
        if sys.platform == "win32":
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
    finally:
        try:
            handle.close()
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="platex-client", description="Clipboard watcher for OCR to LaTeX.")
    parser.add_argument("--config", type=Path, default=None, help=f"Optional YAML config path. Default: {default_config_path()}")
    parser.add_argument("--db-path", type=Path, default=None, help="Optional SQLite database path.")
    parser.add_argument("--script", type=Path, default=None, help="OCR script to mount.")
    parser.add_argument("--log-file", type=Path, default=None, help=f"Optional log file path. Default: {default_log_path()}")
    parser.add_argument("--interval", type=float, default=None, help="Polling interval in seconds.")
    parser.add_argument(
        "--isolate",
        action="store_true",
        help="Strong isolation mode: disable background polling and run OCR only when manually triggered.",
    )
    parser.add_argument(
        "--publish-latex",
        action="store_true",
        help="Publish OCR text directly to the top of the Windows clipboard history.",
    )
    parser.add_argument(
        "--restore-delay",
        type=float,
        default=None,
        help="Deprecated option kept for backward compatibility (no effect).",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="Start clipboard monitoring.")
    subparsers.add_parser("tray", help="Start clipboard monitoring in system tray mode.")

    history_parser = subparsers.add_parser("history", help="Show recent OCR history.")
    history_parser.add_argument("--limit", type=int, default=10)

    subparsers.add_parser("latest", help="Show the latest OCR result.")
    subparsers.add_parser("copy-latest", help="Copy the latest OCR result to the clipboard.")
    subparsers.add_parser("once", help="Run OCR once on the current clipboard image.")
    logs_parser = subparsers.add_parser("logs", help="Show recent log lines.")
    logs_parser.add_argument("--limit", type=int, default=50)
    return parser


def _resolve_runtime_config(args: argparse.Namespace):
    config = load_config(args.config)
    config.apply_environment()

    return {
        "db_path": args.db_path or config.db_path,
        "script": args.script or config.script or _default_script_path(),
        "log_file": args.log_file or config.log_file or default_log_path(),
        "interval": args.interval if args.interval is not None else config.interval,
        "publish_latex": args.publish_latex or config.publish_latex,
        "isolate_mode": args.isolate or config.isolate_mode,
        "restore_delay": args.restore_delay if args.restore_delay is not None else config.restore_delay,
    }


def _print_event(prefix: str, event) -> None:
    if event.status == "ok":
        print(f"{prefix} {event.image_hash[:10]} {event.image_width}x{event.image_height}")
        print(event.latex)
    else:
        print(f"{prefix} {event.image_hash[:10]} failed: {event.error}")


def _serve(args: argparse.Namespace) -> int:
    runtime = _resolve_runtime_config(args)
    setup_logging(runtime["log_file"])
    history = HistoryStore(runtime["db_path"])
    processor = load_script_processor(runtime["script"])
    watcher = ClipboardWatcher(
        processor=processor,
        history=history,
        source_name=str(runtime["script"]),
        on_success=publish_text_to_clipboard if runtime["publish_latex"] else None,
    )

    print(f"Watching clipboard. Mounted script: {runtime['script']}")
    print(f"Logging to: {runtime['log_file']}")
    try:
        while True:
            event = watcher.poll_once()
            if event is not None:
                _print_event("Captured", event)
            time.sleep(runtime["interval"])
    except KeyboardInterrupt:
        print("Stopped.")
    return 0


def _tray(args: argparse.Namespace) -> int:
    if not _acquire_single_instance_lock():
        print("PLatex tray is already running. Please exit the existing tray instance first.")
        return 1

    try:
        runtime = _resolve_runtime_config(args)
        setup_logging(runtime["log_file"])
        app = PlatexApp(
            db_path=runtime["db_path"],
            script_path=runtime["script"],
            interval=runtime["interval"],
            publish_latex=runtime["publish_latex"],
            isolate_mode=runtime["isolate_mode"],
            restore_delay=runtime["restore_delay"],
        )
        history = HistoryStore(runtime["db_path"])
        controller = TrayController(app=app, history=history)
        print(f"Starting tray mode. Mounted script: {runtime['script']}")
        print(f"Logging to: {runtime['log_file']}")
        return controller.run()
    finally:
        _release_single_instance_lock()


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


def _print_logs(runtime: dict[str, object], limit: int) -> int:
    log_file = Path(runtime["log_file"])
    if not log_file.exists():
        print(f"No log file yet: {log_file}")
        return 0

    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    for line in lines[-limit:]:
        print(line)
    return 0


def _once(args: argparse.Namespace) -> int:
    runtime = _resolve_runtime_config(args)
    setup_logging(runtime["log_file"])

    app = PlatexApp(
        db_path=runtime["db_path"],
        script_path=runtime["script"],
        interval=runtime["interval"],
        publish_latex=runtime["publish_latex"],
        isolate_mode=True,
        restore_delay=runtime["restore_delay"],
    )
    event = app.run_once()
    if event is None:
        print("No clipboard image found.")
        return 1

    _print_event("Captured", event)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        argv = ["tray"]

    args = parser.parse_args(argv)

    runtime = _resolve_runtime_config(args)

    if args.command == "serve":
        return _serve(args)
    if args.command == "tray":
        return _tray(args)
    if args.command == "logs":
        return _print_logs(runtime, args.limit)
    if args.command == "once":
        return _once(args)

    history = HistoryStore(runtime["db_path"])
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