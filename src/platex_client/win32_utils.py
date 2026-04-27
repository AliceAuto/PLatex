from __future__ import annotations

import ctypes
import logging
from ctypes import wintypes
from typing import Any

from .platform_utils import IS_WINDOWS, KERNEL32, USER32

logger = logging.getLogger("platex.win32_utils")

ERROR_CLASS_ALREADY_EXISTS = 1410


def make_wndclass_type(wndproc_type: Any) -> type[ctypes.Structure]:
    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", wndproc_type),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HANDLE),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HANDLE),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]
    return WNDCLASSW


def register_window_class(
    class_name: str,
    wnd_proc: Any,
    wndproc_type: Any,
    hinst: int | None = None,
) -> bool:
    if not IS_WINDOWS or USER32 is None:
        return False

    if hinst is None:
        if KERNEL32 is None:
            return False
        hinst = KERNEL32.GetModuleHandleW(None)

    WNDCLASSW = make_wndclass_type(wndproc_type)
    wndclass = WNDCLASSW()
    wndclass.lpfnWndProc = wnd_proc
    wndclass.hInstance = hinst
    wndclass.lpszClassName = class_name
    wndclass.cbClsExtra = 0
    wndclass.cbWndExtra = 0
    wndclass.hIcon = 0
    wndclass.hCursor = 0
    wndclass.hbrBackground = 0
    wndclass.lpszMenuName = None

    if not USER32.RegisterClassW(ctypes.byref(wndclass)):
        err = ctypes.get_last_error()
        if err == ERROR_CLASS_ALREADY_EXISTS:
            USER32.UnregisterClassW(class_name, hinst)
            if not USER32.RegisterClassW(ctypes.byref(wndclass)):
                err2 = ctypes.get_last_error()
                logger.error("Failed to register window class '%s' after retry: error %d", class_name, err2)
                return False
        elif err != 0:
            logger.error("Failed to register window class '%s': error %d", class_name, err)
            return False

    return True


def create_message_window(
    class_name: str,
    window_title: str,
    hinst: int | None = None,
) -> int:
    if not IS_WINDOWS or USER32 is None:
        return 0

    if hinst is None:
        if KERNEL32 is None:
            return 0
        hinst = KERNEL32.GetModuleHandleW(None)

    hwnd = USER32.CreateWindowExW(
        0, class_name, window_title,
        0, 0, 0, 0, 0,
        ctypes.c_void_p(-3),
        None, hinst, None,
    )

    if not hwnd:
        err = ctypes.get_last_error()
        logger.error("Failed to create message window '%s': error %d", class_name, err)
        return 0

    return hwnd


def destroy_message_window(hwnd: int, class_name: str, hinst: int | None = None) -> None:
    if not IS_WINDOWS or USER32 is None:
        return

    if hinst is None:
        if KERNEL32 is not None:
            hinst = KERNEL32.GetModuleHandleW(None)
        else:
            hinst = None

    if hwnd:
        try:
            USER32.DestroyWindow(hwnd)
        except Exception:
            pass
    if hinst is not None:
        try:
            USER32.UnregisterClassW(class_name, hinst)
        except Exception:
            pass
