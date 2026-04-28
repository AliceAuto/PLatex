from __future__ import annotations

import logging
import os
import queue
import threading

from .clipboard import copy_text_to_clipboard
from .events import EventBus, OcrSuccessEvent, ShowPanelEvent, ShutdownRequestEvent, get_event_bus

logger = logging.getLogger("platex.popup_manager")


_MAX_QUEUE_SIZE = 50


class PopupManager:
    def __init__(self, bus: EventBus | None = None) -> None:
        self._popup_queue: queue.Queue[tuple[str, str, int] | None] = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._panel_queue: queue.Queue[str | None] = queue.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._stop_event = threading.Event()
        self._shutdown_confirmed = threading.Event()
        self._shutdown_lock = threading.Lock()
        self._bus = bus or get_event_bus()
        self._active_popups: list[object] = []
        self._app_ref: object | None = None
        self._panel_window: object | None = None

    @property
    def popup_queue(self) -> queue.Queue[tuple[str, str, int] | None]:
        return self._popup_queue

    @property
    def panel_queue(self) -> queue.Queue[str | None]:
        return self._panel_queue

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_event

    def request_shutdown(self) -> None:
        with self._shutdown_lock:
            if self._stop_event.is_set():
                return
            self._stop_event.set()
            try:
                self._popup_queue.put_nowait(None)
            except queue.Full:
                pass
            try:
                self._panel_queue.put_nowait(None)
            except queue.Full:
                pass
        self._bus.emit(ShutdownRequestEvent())

    def wait_for_shutdown(self, timeout: float = 5.0) -> bool:
        """Wait until the shutdown has been confirmed by the consumer.

        Returns True if confirmed within *timeout*, False otherwise.
        """
        return self._shutdown_confirmed.wait(timeout=timeout)

    def confirm_shutdown(self) -> None:
        """Called by the consumer after processing the shutdown sentinel."""
        self._shutdown_confirmed.set()

    def show_popup(self, title: str, latex: str, timeout_ms: int = 12000) -> None:
        if self._stop_event.is_set():
            return
        try:
            self._popup_queue.put_nowait((title, latex, timeout_ms))
        except queue.Full:
            try:
                self._popup_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._popup_queue.put_nowait((title, latex, timeout_ms))
            except queue.Full:
                logger.warning("Popup queue still full after drain, dropping popup")

    def open_panel(self) -> None:
        if self._stop_event.is_set():
            return
        try:
            self._panel_queue.put_nowait("open-panel")
        except queue.Full:
            logger.warning("Panel queue full, dropping open-panel command")
        self._bus.emit(ShowPanelEvent())

    def subscribe_ocr_events(self) -> None:
        self._bus.subscribe(OcrSuccessEvent, self._on_ocr_success)

    def unsubscribe_ocr_events(self) -> None:
        self._bus.unsubscribe(OcrSuccessEvent, self._on_ocr_success)

    def _on_ocr_success(self, event: OcrSuccessEvent) -> None:
        self.show_popup("PLatex OCR Success", event.latex)
        logger.info("OCR success popup emitted hash=%s", event.image_hash[:10])
