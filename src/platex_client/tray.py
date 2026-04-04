from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from .app import PlatexApp
from .clipboard import copy_text_to_clipboard
from .history import HistoryStore


def _load_pystray():
    try:
        import pystray
        from pystray import Menu, MenuItem
    except ImportError as exc:  # pragma: no cover - optional dependency fallback
        raise RuntimeError("pystray is required for tray mode. Install project dependencies first.") from exc

    return pystray, Menu, MenuItem


def _build_icon_image():
    from PIL import Image, ImageDraw

    image = Image.new("RGBA", (64, 64), (20, 24, 31, 255))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((8, 8, 56, 56), radius=12, outline=(122, 162, 255, 255), width=3)
    draw.line((18, 22, 18, 42), fill=(122, 162, 255, 255), width=4)
    draw.line((46, 22, 46, 42), fill=(122, 162, 255, 255), width=4)
    draw.line((18, 42, 32, 30), fill=(122, 162, 255, 255), width=4)
    draw.line((32, 30, 46, 42), fill=(122, 162, 255, 255), width=4)
    return image


@dataclass(slots=True)
class TrayController:
    app: PlatexApp
    history: HistoryStore

    def run(self) -> int:
        logger = logging.getLogger("platex.tray")
        pystray, Menu, MenuItem = _load_pystray()

        def show_status() -> str:
            latest = self.history.latest()
            if latest is None:
                return "PLatex Client | waiting for clipboard image"
            if latest.status == "ok":
                return f"PLatex Client | latest {latest.image_hash[:10]}"
            return f"PLatex Client | last error {latest.error}"

        def copy_latest(_icon, _item) -> None:
            latest = self.history.latest()
            if latest is None or latest.status != "ok" or not latest.latex.strip():
                return
            copy_text_to_clipboard(latest.latex)
            logger.info("Copied latest LaTeX from tray menu")

        def refresh(_icon, _item) -> None:
            icon.title = show_status()

        def quit_app(icon, _item) -> None:
            logger.info("Tray exit requested")
            self.app.stop()
            icon.stop()

        menu = Menu(
            MenuItem("Copy latest LaTeX", copy_latest, default=True),
            MenuItem("Refresh status", refresh),
            MenuItem("Exit", quit_app),
        )
        icon = pystray.Icon("PLatexClient", _build_icon_image(), show_status(), menu)
        self.app.start()
        try:
            icon.run()
        except KeyboardInterrupt:
            logger.info("Tray interrupted by keyboard")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error in tray main loop: %s", exc)
        finally:
            self.app.stop()
        return 0
