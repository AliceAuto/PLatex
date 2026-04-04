from __future__ import annotations

import logging
import signal
import threading
from dataclasses import dataclass
from pathlib import Path

from .app import PlatexApp
from .clipboard import copy_text_to_clipboard
from .history import HistoryStore
from .models import ClipboardEvent


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
        previous_sigint_handler = signal.getsignal(signal.SIGINT)

        def show_click_to_copy_popup(title: str, latex: str, timeout_ms: int = 12000) -> None:
            def worker() -> None:
                try:
                    import tkinter as tk

                    root = tk.Tk()
                    root.title(title)
                    root.attributes("-topmost", True)
                    root.resizable(False, False)

                    # Place near bottom-right corner like a toast.
                    root.update_idletasks()
                    width = 620
                    height = 180
                    x = max(0, root.winfo_screenwidth() - width - 24)
                    y = max(0, root.winfo_screenheight() - height - 72)
                    root.geometry(f"{width}x{height}+{x}+{y}")

                    frame = tk.Frame(root, padx=12, pady=10)
                    frame.pack(fill="both", expand=True)
                    tk.Label(frame, text=title, font=("Segoe UI", 11, "bold"), anchor="w").pack(fill="x")
                    preview = latex.replace("\n", " ").strip()
                    if len(preview) > 220:
                        preview = preview[:217] + "..."
                    message_label = tk.Label(
                        frame,
                        text=preview or "OCR completed",
                        justify="left",
                        anchor="w",
                        wraplength=580,
                        font=("Segoe UI", 10),
                    )
                    message_label.pack(fill="both", expand=True, pady=(6, 0))
                    status_label = tk.Label(
                        frame,
                        text="点击弹窗任意位置复制公式",
                        justify="left",
                        anchor="w",
                        wraplength=580,
                        font=("Segoe UI", 9),
                        fg="#666666",
                    )
                    status_label.pack(fill="x", pady=(0, 6))

                    copied = {"done": False}

                    def copy_and_close(_event=None) -> None:
                        if copied["done"]:
                            return
                        try:
                            copy_text_to_clipboard(latex)
                            copied["done"] = True
                            status_label.config(text="已复制到剪贴板")
                            logger.info("Copied OCR result from popup")
                            root.after(500, root.destroy)
                        except Exception as exc:  # noqa: BLE001
                            logger.exception("Popup copy failed: %s", exc)
                            status_label.config(text="复制失败，请重试")

                    root.bind("<Button-1>", copy_and_close)
                    frame.bind("<Button-1>", copy_and_close)
                    message_label.bind("<Button-1>", copy_and_close)
                    status_label.bind("<Button-1>", copy_and_close)

                    button_row = tk.Frame(frame)
                    button_row.pack(fill="x")
                    tk.Button(button_row, text="点击复制", command=copy_and_close).pack(side="right")

                    root.after(timeout_ms, root.destroy)
                    root.mainloop()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Fallback popup failed: %s", exc)

            threading.Thread(target=worker, name="platex-toast-popup", daemon=True).start()

        def show_status() -> str:
            latest = self.history.latest()
            mode = "isolated" if self.app.isolate_mode else "watching"
            if latest is None:
                return f"PLatex Client | {mode} | waiting for clipboard image"
            if latest.status == "ok":
                return f"PLatex Client | {mode} | latest {latest.image_hash[:10]}"
            return f"PLatex Client | {mode} | last error {latest.error}"

        def ocr_once(_icon, _item) -> None:
            event = self.app.run_once()
            if event is None:
                logger.info("Manual OCR once: no clipboard image found")
            elif event.status == "ok":
                logger.info("Manual OCR once success: %s", event.image_hash[:10])
            else:
                logger.warning("Manual OCR once failed: %s", event.error)
            icon.title = show_status()

        def notify_success(event: ClipboardEvent) -> None:
            show_click_to_copy_popup("PLatex OCR Success", event.latex)
            logger.info("OCR success popup emitted hash=%s", event.image_hash[:10])

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
            MenuItem("OCR once now", ocr_once),
            MenuItem("Copy latest LaTeX", copy_latest, default=True),
            MenuItem("Refresh status", refresh),
            MenuItem("Exit", quit_app),
        )
        icon = pystray.Icon("PLatexClient", _build_icon_image(), show_status(), menu)
        self.app.on_ocr_success = notify_success
        self.app.start()
        try:
            # In console-launched tray mode, Ctrl+C can bubble into pystray Win32 callbacks
            # and print noisy "Exception ignored on calling ctypes callback" traces.
            # Ignore SIGINT and let users exit from tray menu for a clean shutdown.
            signal.signal(signal.SIGINT, signal.SIG_IGN)
            icon.run()
        except KeyboardInterrupt:
            logger.info("Tray interrupted by keyboard")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error in tray main loop: %s", exc)
        finally:
            signal.signal(signal.SIGINT, previous_sigint_handler)
            self.app.stop()
        return 0
