from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from platformdirs import user_data_dir


def _bootstrap_log_path() -> Path:
    log_dir = Path(user_data_dir("PLatexClient", "Copilot")) / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "startup.log"


def _append_startup_log(message: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _bootstrap_log_path().open("a", encoding="utf-8") as handle:
            handle.write(f"[{ts}] {message}\n")
    except Exception:
        # Startup logging must never block app launch.
        pass


def _install_global_excepthook() -> None:
    def _hook(exc_type, exc_value, exc_tb) -> None:
        detail = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _append_startup_log("UNHANDLED_EXCEPTION\n" + detail)

    sys.excepthook = _hook


def _run() -> int:
    _install_global_excepthook()
    _append_startup_log(
        "BOOT "
        f"python={sys.version.split()[0]} "
        f"frozen={getattr(sys, 'frozen', False)} "
        f"exe={sys.executable} "
        f"cwd={os.getcwd()} "
        f"argv={sys.argv}"
    )

    try:
        from platex_client.cli import main

        code = int(main())
        _append_startup_log(f"EXIT code={code}")
        return code
    except Exception:  # noqa: BLE001
        _append_startup_log("FATAL\n" + traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(_run())
