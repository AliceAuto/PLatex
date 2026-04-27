from __future__ import annotations

import argparse
import ctypes
import sys
import time
from pathlib import Path

from platformdirs import user_data_dir
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

if sys.platform == "win32":
    import msvcrt


_INSTANCE_LOCK_HANDLE = None
_INSTANCE_PANEL_EVENT_NAME = r"Local\PLatexClient_ShowControlPanel"

if sys.platform == "win32":
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _EVENT_MODIFY_STATE = 0x0002
    _SYNCHRONIZE = 0x00100000

_console = Console()


def _enable_windows_dpi_awareness() -> None:
    from .platform_utils import enable_dpi_awareness
    enable_dpi_awareness()


def _signal_existing_instance_panel() -> bool:
    from .platform_utils import signal_existing_instance_panel
    return signal_existing_instance_panel()


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


def _default_script_path() -> Path:
    script_name = Path("scripts") / "glm_vision_ocr.py"

    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / script_name)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / script_name)

    candidates.append(Path(__file__).resolve().parents[2] / script_name)

    for candidate in candidates:
        if candidate.exists():
            return candidate

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


def _print_banner() -> None:
    from . import __version__
    _console.print(
        Panel(
            Text.from_markup(
                f"[bold cyan]PLatex Client[/] [dim]v{__version__}[/]\n"
                "[dim]Clipboard OCR → LaTeX assistant[/]"
            ),
            border_style="cyan",
            padding=(0, 2),
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="platex-client",
        description="Clipboard watcher for OCR to LaTeX.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  platex-client tray --gui     Start with system tray & open panel\n"
            "  platex-client serve           Start in console mode\n"
            "  platex-client once            Run OCR once on clipboard\n"
            "  platex-client history --limit 20   Show last 20 records\n"
            "  platex-client copy-latest     Copy latest LaTeX to clipboard\n"
        ),
    )
    parser.add_argument("--config", type=Path, default=None, help=f"YAML config path (default: {default_config_path()})")
    parser.add_argument("--db-path", type=Path, default=None, help="SQLite database path")
    parser.add_argument("--script", type=Path, default=None, help="OCR script to mount")
    parser.add_argument("--log-file", type=Path, default=None, help=f"Log file path (default: {default_log_path()})")
    parser.add_argument("--interval", type=float, default=None, help="Polling interval in seconds")
    parser.add_argument(
        "--isolate",
        action="store_true",
        help="Disable background polling; OCR only on manual trigger",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="Start clipboard monitoring (console)")
    tray_parser = subparsers.add_parser("tray", help="Start with system tray")
    tray_parser.add_argument("--gui", action="store_true", help="Open control panel on startup")
    subparsers.add_parser("panel", help="Open control panel (starts tray if needed)")

    history_parser = subparsers.add_parser("history", help="Show recent OCR history")
    history_parser.add_argument("--limit", type=int, default=10)

    subparsers.add_parser("latest", help="Show the latest OCR result")
    subparsers.add_parser("copy-latest", help="Copy latest OCR result to clipboard")
    subparsers.add_parser("once", help="Run OCR once on current clipboard image")
    logs_parser = subparsers.add_parser("logs", help="Show recent log lines")
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
        "isolate_mode": args.isolate or config.isolate_mode,
    }


def _print_event(prefix: str, event) -> None:
    if event.status == "ok":
        _console.print(
            f"[bold green]{prefix}[/] "
            f"[dim]{event.image_hash[:10]}[/] "
            f"[cyan]{event.image_width}x{event.image_height}[/]"
        )
        _console.print(Panel(event.latex, border_style="green", padding=(0, 1)))
    else:
        _console.print(
            f"[bold red]{prefix}[/] "
            f"[dim]{event.image_hash[:10]}[/] "
            f"[red]failed: {event.error}[/]"
        )


def _serve(runtime: dict) -> int:
    _enable_windows_dpi_awareness()
    setup_logging(runtime["log_file"])
    _print_banner()

    history = HistoryStore(runtime["db_path"])
    processor = load_script_processor(runtime["script"])
    watcher = ClipboardWatcher(
        processor=processor,
        history=history,
        source_name=str(runtime["script"]),
    )

    _console.print(
        Panel(
            Text.from_markup(
                f"[bold]Script:[/]  {runtime['script']}\n"
                f"[bold]Log:[/]     {runtime['log_file']}\n"
                f"[bold]Interval:[/] {runtime['interval']}s"
            ),
            title="[bold]Watching Clipboard[/]",
            border_style="cyan",
            padding=(0, 1),
        )
    )
    try:
        while True:
            event = watcher.poll_once()
            if event is not None:
                _print_event("Captured", event)
            time.sleep(runtime["interval"])
    except KeyboardInterrupt:
        _console.print("[bold yellow]Stopped.[/]")
    finally:
        watcher.close()
    return 0


def _tray(runtime: dict, *, open_panel_on_start: bool = False) -> int:
    _enable_windows_dpi_awareness()
    if not _acquire_single_instance_lock():
        _signal_existing_instance_panel()
        _console.print("[bold yellow]PLatex tray is already running. Activated the existing instance.[/]")
        return 0

    try:
        setup_logging(runtime["log_file"])
        from .i18n import initialize as init_i18n
        from .config import load_config

        config = load_config()
        init_i18n(config.ui_language)

        _print_banner()
        app = PlatexApp(
            db_path=runtime["db_path"],
            script_path=runtime["script"],
            interval=runtime["interval"],
            isolate_mode=runtime["isolate_mode"],
        )
        history = HistoryStore(runtime["db_path"])
        app.set_external_history(history)
        controller = TrayController(app=app, history=history)
        _console.print(
            Panel(
                Text.from_markup(
                    f"[bold]Script:[/]  {runtime['script']}\n"
                    f"[bold]Log:[/]     {runtime['log_file']}"
                ),
                title="[bold]Tray Mode[/]",
                border_style="cyan",
                padding=(0, 1),
            )
        )
        return controller.run(open_panel_on_start=open_panel_on_start)
    finally:
        _release_single_instance_lock()


def _print_history(history: HistoryStore, limit: int) -> int:
    records = history.list_recent(limit=limit)
    if not records:
        _console.print("[dim]No history yet.[/]")
        return 0

    table = Table(
        title="OCR History",
        show_lines=False,
        border_style="cyan",
        header_style="bold cyan",
        row_styles=["", "dim"],
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Time", style="dim", width=20)
    table.add_column("Hash", style="dim", width=10)
    table.add_column("Size", style="cyan", width=10)
    table.add_column("Result", min_width=30)

    for index, record in enumerate(records, start=1):
        time_str = record.created_at.strftime("%Y-%m-%d %H:%M:%S")
        hash_str = record.image_hash[:10]
        size_str = f"{record.image_width}x{record.image_height}"
        if record.status == "ok":
            latex_preview = record.latex[:80] + ("..." if len(record.latex) > 80 else "")
            table.add_row(str(index), time_str, hash_str, size_str, latex_preview)
        else:
            table.add_row(str(index), time_str, hash_str, size_str, f"[red]error: {record.error}[/]")

    _console.print(table)

    for index, record in enumerate(records, start=1):
        if record.status == "ok" and record.latex:
            _console.print(
                Panel(
                    record.latex,
                    title=f"[dim]#{index}[/]",
                    border_style="green",
                    padding=(0, 1),
                )
            )

    return 0


def _print_latest(history: HistoryStore) -> int:
    record = history.latest()
    if record is None:
        _console.print("[dim]No history yet.[/]")
        return 0

    _print_event("Latest", record)
    return 0


def _copy_latest(history: HistoryStore) -> int:
    record = history.latest()
    if record is None or record.status != "ok" or not record.latex.strip():
        _console.print("[bold red]No successful OCR result to copy.[/]")
        return 1

    copy_text_to_clipboard(record.latex)
    _console.print("[bold green]Copied latest LaTeX result to clipboard.[/]")
    return 0


def _print_logs(runtime: dict[str, object], limit: int) -> int:
    log_file = Path(runtime["log_file"])
    if not log_file.exists():
        _console.print(f"[dim]No log file yet: {log_file}[/]")
        return 0

    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-limit:]

    for line in tail:
        _style_line(line)

    return 0


def _style_line(line: str) -> None:
    upper = line.upper()
    if " | DEBUG " in upper or "DEBUG:" in upper:
        _console.print(f"[dim]{line}[/]")
    elif " | WARNING " in upper or "WARNING:" in upper:
        _console.print(f"[yellow]{line}[/]")
    elif " | ERROR " in upper or "ERROR:" in upper:
        _console.print(f"[bold red]{line}[/]")
    elif " | CRITICAL " in upper or "CRITICAL:" in upper:
        _console.print(f"[bold red on white]{line}[/]")
    else:
        _console.print(line)


def _once(runtime: dict) -> int:
    setup_logging(runtime["log_file"])

    app = PlatexApp(
        db_path=runtime["db_path"],
        script_path=runtime["script"],
        interval=runtime["interval"],
        isolate_mode=True,
    )
    try:
        event = app.run_once()
    finally:
        try:
            app.stop()
        except Exception:
            pass
    if event is None:
        _console.print("[bold yellow]No clipboard image found.[/]")
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
        return _serve(runtime)
    if args.command == "tray":
        return _tray(runtime, open_panel_on_start=getattr(args, "gui", False))
    if args.command == "panel":
        return _tray(runtime, open_panel_on_start=True)
    if args.command == "logs":
        return _print_logs(runtime, args.limit)
    if args.command == "once":
        return _once(runtime)

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
