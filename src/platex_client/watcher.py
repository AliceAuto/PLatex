from __future__ import annotations

import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .clipboard import grab_image_clipboard, image_hash
from .history import HistoryStore
from .models import ClipboardEvent, OcrProcessor

_MAX_ORPHAN_THREADS = 5


def _init_com_for_thread() -> None:
    try:
        import ctypes
        ctypes.windll.ole32.CoInitializeEx(None, 0x0)
    except Exception:
        pass


def _uninit_com_for_thread() -> None:
    try:
        import ctypes
        ctypes.windll.ole32.CoUninitialize()
    except Exception:
        pass


@dataclass(slots=True)
class ClipboardWatcher:
    processor: OcrProcessor
    history: HistoryStore
    source_name: str
    ocr_timeout: float = 120.0
    last_image_hash: str | None = None
    _processing_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _ocr_running: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _paused: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _orphan_threads: list[threading.Thread] = field(default_factory=list, init=False, repr=False)
    _orphan_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("platex.watcher"), init=False, repr=False)

    def __post_init__(self) -> None:
        pass

    def set_publishing(self, is_publishing: bool) -> None:
        if is_publishing:
            self._paused.set()
        else:
            self._paused.clear()

    def _cleanup_orphan_threads(self) -> None:
        with self._orphan_lock:
            self._orphan_threads = [t for t in self._orphan_threads if t.is_alive()]
            if len(self._orphan_threads) > _MAX_ORPHAN_THREADS:
                self.logger.warning(
                    "Too many orphan OCR threads (%d), some may be stuck",
                    len(self._orphan_threads),
                )

    def poll_once(self, *, force: bool = False) -> ClipboardEvent | None:
        if self._paused.is_set():
            self.logger.debug("Skipping poll during clipboard publish/restore")
            return None

        if self._ocr_running.is_set():
            self.logger.debug("Skipping poll: OCR already in progress")
            return None

        image = grab_image_clipboard()
        if image is None:
            self.logger.debug("Clipboard poll found no image content")
            return None

        current_hash = image_hash(image.image_bytes)

        with self._processing_lock:
            if self._paused.is_set():
                return None

            if self._ocr_running.is_set():
                return None

            if not force and current_hash == self.last_image_hash:
                self.logger.debug("Skipping already processed clipboard image: %s", current_hash[:10])
                return None

            self.last_image_hash = current_hash
            self._ocr_running.set()

        self._cleanup_orphan_threads()

        now = datetime.now(timezone.utc)
        self.logger.info("OCR start hash=%s size=%dx%d source=%s", current_hash[:10], image.width, image.height, self.source_name)

        ocr_queue: queue.Queue[tuple[str, str] | tuple[str, Exception]] = queue.Queue()

        def _run_ocr() -> None:
            _init_com_for_thread()
            try:
                result = self.processor.process_image(
                    image.image_bytes,
                    context={
                        "image_hash": current_hash,
                        "image_width": image.width,
                        "image_height": image.height,
                        "source": self.source_name,
                    },
                )
                ocr_queue.put(("ok", result))
            except Exception as exc:
                ocr_queue.put(("error", exc))
            finally:
                _uninit_com_for_thread()

        ocr_thread = threading.Thread(target=_run_ocr, name="platex-ocr-worker", daemon=True)
        ocr_thread.start()
        ocr_thread.join(timeout=self.ocr_timeout)

        event: ClipboardEvent | None = None
        try:
            if ocr_thread.is_alive():
                self.logger.error("OCR timed out after %.0fs hash=%s", self.ocr_timeout, current_hash[:10])
                with self._orphan_lock:
                    self._orphan_threads.append(ocr_thread)
                event = ClipboardEvent(
                    created_at=now,
                    image_hash=current_hash,
                    image_width=image.width,
                    image_height=image.height,
                    latex="",
                    source=self.source_name,
                    status="error",
                    error=f"OCR timed out after {self.ocr_timeout}s",
                )
            else:
                try:
                    ocr_status, ocr_value = ocr_queue.get_nowait()
                except queue.Empty:
                    self.logger.error("OCR thread completed but produced no result hash=%s", current_hash[:10])
                    ocr_status, ocr_value = "error", RuntimeError("OCR thread produced no result")
                if ocr_status == "error":
                    exc = ocr_value
                    self.logger.error("OCR failed hash=%s: %s", current_hash[:10], exc)
                    event = ClipboardEvent(
                        created_at=now,
                        image_hash=current_hash,
                        image_width=image.width,
                        image_height=image.height,
                        latex="",
                        source=self.source_name,
                        status="error",
                        error=str(exc),
                    )
                else:
                    latex = ocr_value
                    event = ClipboardEvent(
                        created_at=now,
                        image_hash=current_hash,
                        image_width=image.width,
                        image_height=image.height,
                        latex=latex,
                        source=self.source_name,
                        status="ok",
                        error=None,
                    )
                    self.logger.info("OCR success hash=%s latex=%s", current_hash[:10], latex[:120].replace("\n", " "))
        except Exception:
            self.logger.exception("Unexpected error processing OCR result for hash=%s", current_hash[:10])
            event = ClipboardEvent(
                created_at=now,
                image_hash=current_hash,
                image_width=image.width,
                image_height=image.height,
                latex="",
                source=self.source_name,
                status="error",
                error="Unexpected error processing OCR result",
            )
        finally:
            with self._processing_lock:
                self._ocr_running.clear()

        if event is not None and self.history is not None:
            try:
                self.history.add(event)
            except Exception as db_exc:
                self.logger.error("Failed to persist event to history: %s", db_exc)

        return event

    def poll_once_async(self, callback: Callable[[ClipboardEvent | None], None], *, force: bool = False) -> bool:
        if self._paused.is_set():
            self.logger.debug("Skipping async poll during clipboard publish/restore")
            return False

        if self._ocr_running.is_set():
            self.logger.debug("Skipping async poll: OCR already in progress")
            return False

        image = grab_image_clipboard()
        if image is None:
            self.logger.debug("Async poll found no image content")
            return False

        current_hash = image_hash(image.image_bytes)

        with self._processing_lock:
            if self._paused.is_set():
                return False

            if self._ocr_running.is_set():
                return False

            if not force and current_hash == self.last_image_hash:
                self.logger.debug("Skipping already processed clipboard image: %s", current_hash[:10])
                return False

            self.last_image_hash = current_hash
            self._ocr_running.set()

        self._cleanup_orphan_threads()

        now = datetime.now(timezone.utc)
        self.logger.info("Async OCR start hash=%s size=%dx%d source=%s", current_hash[:10], image.width, image.height, self.source_name)

        _ocr_done = threading.Event()
        _result_lock = threading.Lock()
        _result_delivered = False

        def _deliver_result(event: ClipboardEvent | None) -> None:
            nonlocal _result_delivered
            with _result_lock:
                if _result_delivered:
                    return
                _result_delivered = True

            if event is not None and self.history is not None:
                try:
                    self.history.add(event)
                except Exception as db_exc:
                    self.logger.error("Failed to persist event to history: %s", db_exc)

            try:
                callback(event)
            except Exception:
                self.logger.exception("Error in async OCR callback for hash=%s", current_hash[:10])

        def _run_ocr_and_notify() -> None:
            _init_com_for_thread()
            event: ClipboardEvent | None = None
            try:
                result = self.processor.process_image(
                    image.image_bytes,
                    context={
                        "image_hash": current_hash,
                        "image_width": image.width,
                        "image_height": image.height,
                        "source": self.source_name,
                    },
                )
                event = ClipboardEvent(
                    created_at=now,
                    image_hash=current_hash,
                    image_width=image.width,
                    image_height=image.height,
                    latex=result,
                    source=self.source_name,
                    status="ok",
                    error=None,
                )
                self.logger.info("Async OCR success hash=%s latex=%s", current_hash[:10], result[:120].replace("\n", " "))
            except Exception as exc:
                self.logger.error("Async OCR failed hash=%s: %s", current_hash[:10], exc)
                event = ClipboardEvent(
                    created_at=now,
                    image_hash=current_hash,
                    image_width=image.width,
                    image_height=image.height,
                    latex="",
                    source=self.source_name,
                    status="error",
                    error=str(exc),
                )
            finally:
                _ocr_done.set()
                with self._processing_lock:
                    self._ocr_running.clear()
                _uninit_com_for_thread()

            _deliver_result(event)

        def _ocr_watchdog() -> None:
            if _ocr_done.wait(timeout=self.ocr_timeout):
                return
            if not self._ocr_running.is_set():
                return
            with _result_lock:
                if _result_delivered:
                    return
            self.logger.error("Async OCR timed out after %.0fs hash=%s", self.ocr_timeout, current_hash[:10])
            with self._processing_lock:
                self._ocr_running.clear()
            timeout_event = ClipboardEvent(
                created_at=now,
                image_hash=current_hash,
                image_width=image.width,
                image_height=image.height,
                latex="",
                source=self.source_name,
                status="error",
                error=f"OCR timed out after {self.ocr_timeout}s",
            )
            _deliver_result(timeout_event)

        ocr_thread = threading.Thread(target=_run_ocr_and_notify, name="platex-ocr-worker", daemon=True)
        ocr_thread.start()

        watchdog_thread = threading.Thread(target=_ocr_watchdog, name="platex-ocr-watchdog", daemon=True)
        watchdog_thread.start()

        with self._orphan_lock:
            self._orphan_threads.append(ocr_thread)

        return True

    _CLOSE_WAIT_TIMEOUT = 5.0

    def close(self) -> None:
        if self._ocr_running.is_set():
            self.logger.info("Waiting for in-progress OCR to complete before closing...")
            deadline = time.monotonic() + min(self.ocr_timeout + 5.0, self._CLOSE_WAIT_TIMEOUT)
            while self._ocr_running.is_set() and time.monotonic() < deadline:
                time.sleep(0.1)
            if self._ocr_running.is_set():
                self.logger.warning("OCR still running after close timeout, forcing _ocr_running clear")
                self._ocr_running.clear()

        with self._orphan_lock:
            alive_orphans = [t for t in self._orphan_threads if t.is_alive()]
            if alive_orphans:
                self.logger.warning(
                    "Waiting for %d orphan OCR thread(s) to finish (max %.0fs)",
                    len(alive_orphans),
                    5.0,
                )
                for t in alive_orphans:
                    t.join(timeout=5.0 / max(len(alive_orphans), 1))
                still_alive = [t for t in alive_orphans if t.is_alive()]
                if still_alive:
                    self.logger.warning(
                        "%d OCR thread(s) still alive after wait; they are daemon threads and will be killed on exit",
                        len(still_alive),
                    )
                self._orphan_threads.clear()

        if self.history is not None:
            try:
                self.history.close()
            except Exception:
                self.logger.exception("Error closing history store")
