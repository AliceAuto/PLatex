from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from .models import ClipboardEvent, ClipboardImage


class ClipboardAPI:
    """Read and write clipboard content.

    Example::

        ctx.clipboard.write_text("hello")
        text = ctx.clipboard.read_text()
    """

    def __init__(self, *, read_text_fn: Callable[[], str | None],
                 write_text_fn: Callable[[str], None],
                 read_image_fn: Callable[[], ClipboardImage | None]) -> None:
        self._read_text = read_text_fn
        self._write_text = write_text_fn
        self._read_image = read_image_fn

    def read_text(self) -> str | None:
        """Read the current text content from the clipboard.

        Returns the text string, or ``None`` if the clipboard does not
        contain text or the read failed.
        """
        return self._read_text()

    def write_text(self, text: str) -> None:
        """Write text to the clipboard, replacing its current content."""
        self._write_text(text)

    def read_image(self) -> ClipboardImage | None:
        """Read the current image from the clipboard.

        Returns a :class:`ClipboardImage`, or ``None`` if the clipboard
        does not contain an image.
        """
        return self._read_image()


class HotkeyAPI:
    """Register and unregister global hotkeys at runtime.

    Example::

        ctx.hotkeys.register("Ctrl+Alt+K", my_callback)
        ctx.hotkeys.unregister("Ctrl+Alt+K")
    """

    def __init__(self, *, register_fn: Callable[[str, Callable[[], None]], bool],
                 unregister_fn: Callable[[str], None]) -> None:
        self._register = register_fn
        self._unregister = unregister_fn

    def register(self, hotkey: str, callback: Callable[[], None]) -> bool:
        """Register a global hotkey.

        *hotkey* uses human-friendly format: ``"Ctrl+Alt+1"``,
        ``"Ctrl+Shift+F5"``.

        Returns ``True`` if registration succeeded, ``False`` otherwise
        (e.g. the hotkey is already in use by another application).
        """
        return self._register(hotkey, callback)

    def unregister(self, hotkey: str) -> None:
        """Unregister a previously registered global hotkey."""
        self._unregister(hotkey)


class NotificationAPI:
    """Show popup notifications to the user.

    Example::

        ctx.notifications.show("Title", "Message body")
        ctx.notifications.show_ocr_result(latex_text)
    """

    def __init__(self, *, show_fn: Callable[[str, str, int], None],
                 show_ocr_fn: Callable[[str, int], None]) -> None:
        self._show = show_fn
        self._show_ocr = show_ocr_fn

    def show(self, title: str, message: str, *, timeout_ms: int = 5000) -> None:
        """Show a popup notification.

        *timeout_ms* controls how long the popup stays visible before
        auto-fading (default 5 seconds).
        """
        self._show(title, message, timeout_ms)

    def show_ocr_result(self, latex: str, *, timeout_ms: int = 12000) -> None:
        """Show an OCR result popup. Clicking the popup copies the
        LaTeX text to the clipboard.
        """
        self._show_ocr(latex, timeout_ms)


class WindowAPI:
    """Query desktop window information.

    Example::

        title = ctx.windows.get_foreground_title()
    """

    def __init__(self, *, get_foreground_title_fn: Callable[[], str]) -> None:
        self._get_fg_title = get_foreground_title_fn

    def get_foreground_title(self) -> str:
        """Return the title of the current foreground window.

        Returns an empty string if the information is unavailable.
        """
        return self._get_fg_title()


class MouseAPI:
    """Simulate mouse input.

    Example::

        ctx.mouse.click(500, 300, button="left")
    """

    def __init__(self, *, click_fn: Callable[[int, int, str], None]) -> None:
        self._click = click_fn

    def click(self, x: int, y: int, button: str = "left") -> None:
        """Simulate a mouse click at screen coordinates (*x*, *y*).

        *button* is ``"left"`` (default) or ``"right"``.
        The cursor is restored to its original position after clicking.
        """
        self._click(x, y, button)


class _ScheduledTask:
    """A handle returned by :meth:`SchedulerAPI.schedule_once` and
    :meth:`SchedulerAPI.schedule_repeating`.

    Call :meth:`cancel` to stop a pending or repeating task.
    """

    def __init__(self, timer: threading.Timer | None, *, repeating: bool = False,
                 reschedule_fn: Callable[[], None] | None = None) -> None:
        self._timer_lock = threading.Lock()
        self._timer = timer
        self._repeating = repeating
        self._reschedule_fn = reschedule_fn
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        """Cancel this scheduled task."""
        self._cancelled.set()
        with self._timer_lock:
            if self._timer is not None:
                self._timer.cancel()
        if self._reschedule_fn is not None:
            self._reschedule_fn = None

    def set_timer(self, timer: threading.Timer) -> None:
        """Atomically set the timer, respecting cancellation."""
        with self._timer_lock:
            if self._cancelled.is_set():
                timer.cancel()
                return
            self._timer = timer

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()


class SchedulerAPI:
    """Schedule callbacks to run after a delay or on a repeating interval.

    Example::

        task = ctx.scheduler.schedule_once(2.0, lambda: print("2s elapsed"))
        task.cancel()

        periodic = ctx.scheduler.schedule_repeating(5.0, lambda: print("tick"))
    """

    _MAX_TASKS = 64
    _MIN_DELAY = 0.05

    def __init__(self) -> None:
        self._tasks: list[_ScheduledTask] = []
        self._lock = threading.Lock()

    def schedule_once(self, delay: float, callback: Callable[[], None]) -> _ScheduledTask:
        """Schedule *callback* to run once after *delay* seconds.

        Returns a :class:`_ScheduledTask` handle that can be cancelled.
        """
        delay = max(delay, self._MIN_DELAY)

        def _wrapped() -> None:
            with self._lock:
                if task.is_cancelled:
                    return
                try:
                    self._tasks.remove(task)
                except ValueError:
                    return
            try:
                callback()
            except Exception:
                logging.getLogger("platex.scheduler").exception("Error in scheduled callback")

        timer = threading.Timer(delay, _wrapped)
        timer.daemon = True
        task = _ScheduledTask(timer)
        with self._lock:
            self._purge_cancelled()
            if len(self._tasks) >= self._MAX_TASKS:
                self._purge_cancelled()
            if len(self._tasks) >= self._MAX_TASKS:
                raise RuntimeError(
                    f"Scheduler task limit reached ({self._MAX_TASKS}). "
                    "Cancel existing tasks before scheduling new ones."
                )
            self._tasks.append(task)
        timer.start()
        return task

    def schedule_repeating(self, interval: float, callback: Callable[[], None]) -> _ScheduledTask:
        """Schedule *callback* to run every *interval* seconds.

        Returns a :class:`_ScheduledTask` handle.  Call
        ``task.cancel()`` to stop the repetition.
        """
        interval = max(interval, self._MIN_DELAY)

        def _run_step(task: _ScheduledTask) -> None:
            if task.is_cancelled:
                return
            try:
                callback()
            except Exception:
                logging.getLogger("platex.scheduler").exception("Error in repeating scheduled callback")
            if not task.is_cancelled:
                next_timer = threading.Timer(interval, _run_step, args=(task,))
                next_timer.daemon = True
                task.set_timer(next_timer)
                next_timer.start()
            with self._lock:
                self._purge_cancelled()

        task = _ScheduledTask(None, repeating=True)
        with self._lock:
            self._purge_cancelled()
            if len(self._tasks) >= self._MAX_TASKS:
                self._purge_cancelled()
            if len(self._tasks) >= self._MAX_TASKS:
                raise RuntimeError(
                    f"Scheduler task limit reached ({self._MAX_TASKS}). "
                    "Cancel existing tasks before scheduling new ones."
                )
            self._tasks.append(task)

        first_timer = threading.Timer(interval, _run_step, args=(task,))
        first_timer.daemon = True
        task.set_timer(first_timer)
        first_timer.start()
        return task

    def _purge_cancelled(self) -> None:
        if not self._tasks:
            return
        self._tasks = [t for t in self._tasks if not t.is_cancelled]

    def cancel_all(self) -> None:
        """Cancel all scheduled tasks."""
        with self._lock:
            for task in self._tasks:
                task.cancel()
            self._tasks.clear()


class HistoryAPI:
    """Query OCR recognition history.

    Example::

        latest = ctx.history.latest()
        recent = ctx.history.list_recent(limit=10)
    """

    def __init__(self, *, latest_fn: Callable[[], ClipboardEvent | None],
                 list_recent_fn: Callable[[int], list[ClipboardEvent]]) -> None:
        self._latest = latest_fn
        self._list_recent = list_recent_fn

    def latest(self) -> ClipboardEvent | None:
        """Return the most recent OCR event, or ``None`` if no history."""
        return self._latest()

    def list_recent(self, limit: int = 20) -> list[ClipboardEvent]:
        """Return the *limit* most recent OCR events (newest first)."""
        return self._list_recent(limit)


class ConfigAPI:
    """Access script-specific configuration at runtime.

    Example::

        val = ctx.config.get("threshold", default=0.5)
        ctx.config.set("threshold", 0.8)
        ctx.config.save()
    """

    def __init__(self, *, get_fn: Callable[[str, Any], Any],
                 set_fn: Callable[[str, Any], None],
                 save_fn: Callable[[], None],
                 get_all_fn: Callable[[], dict[str, Any]]) -> None:
        self._get = get_fn
        self._set = set_fn
        self._save = save_fn
        self._get_all = get_all_fn

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value by *key*, returning *default* if absent."""
        return self._get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value. Call :meth:`save` to persist."""
        self._set(key, value)

    def save(self) -> None:
        """Persist the current configuration to disk."""
        self._save()

    def get_all(self) -> dict[str, Any]:
        """Return the full configuration dictionary for this script."""
        return self._get_all()


class LoggerAPI:
    """Obtain named loggers for structured logging.

    Example::

        log = ctx.logger.get("my_script")
        log.info("something happened")
    """

    def __init__(self) -> None:
        pass

    def get(self, name: str) -> logging.Logger:
        """Return a :class:`logging.Logger` with the given *name*."""
        return logging.getLogger(f"platex.script.{name}")


class ScriptContext:
    """Stable, high-level API surface available to every script.

    A ``ScriptContext`` is created by the application and injected into
    each script via :meth:`ScriptBase.on_context_ready`.  Scripts
    should store the reference and use it to interact with the
    framework.

    Attributes:
        clipboard: Read/write clipboard content.
        hotkeys: Register/unregister global hotkeys.
        notifications: Show popup notifications.
        windows: Query desktop window information.
        mouse: Simulate mouse input.
        scheduler: Schedule delayed or repeating callbacks.
        history: Query OCR history.
        config: Access script-specific configuration.
        logger: Obtain named loggers.
    """

    def __init__(self, *,
                 clipboard: ClipboardAPI,
                 hotkeys: HotkeyAPI,
                 notifications: NotificationAPI,
                 windows: WindowAPI,
                 mouse: MouseAPI,
                 scheduler: SchedulerAPI,
                 history: HistoryAPI,
                 config: ConfigAPI,
                 logger: LoggerAPI) -> None:
        self.clipboard = clipboard
        self.hotkeys = hotkeys
        self.notifications = notifications
        self.windows = windows
        self.mouse = mouse
        self.scheduler = scheduler
        self.history = history
        self.config = config
        self.logger = logger

    def shutdown(self) -> None:
        self.scheduler.cancel_all()
