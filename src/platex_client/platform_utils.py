from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any

IS_WINDOWS = sys.platform == "win32"

USER32: Any = None
KERNEL32: Any = None

if IS_WINDOWS:
    try:
        USER32 = ctypes.WinDLL("user32", use_last_error=True)
        KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
    except (ImportError, OSError):
        IS_WINDOWS = False

if IS_WINDOWS:
    from ctypes import wintypes

    _user32 = USER32
    _kernel32 = KERNEL32

    _user32.RegisterClassW.argtypes = [ctypes.c_void_p]
    _user32.RegisterClassW.restype = wintypes.ATOM

    _user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    _user32.UnregisterClassW.restype = wintypes.BOOL

    _user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR,
        wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p,
    ]
    _user32.CreateWindowExW.restype = wintypes.HWND

    _user32.DestroyWindow.argtypes = [wintypes.HWND]
    _user32.DestroyWindow.restype = wintypes.BOOL

    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = wintypes.BOOL

    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.TranslateMessage.restype = wintypes.BOOL

    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    _user32.DispatchMessageW.restype = ctypes.c_ssize_t

    _user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.DefWindowProcW.restype = ctypes.c_ssize_t

    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL

    _user32.PostQuitMessage.argtypes = [ctypes.c_int]
    _user32.PostQuitMessage.restype = None

    _user32.OpenClipboard.argtypes = [ctypes.c_void_p]
    _user32.OpenClipboard.restype = ctypes.c_bool
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = ctypes.c_bool
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = ctypes.c_bool
    _user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    _user32.SetClipboardData.restype = ctypes.c_void_p
    _user32.GetClipboardData.argtypes = [ctypes.c_uint]
    _user32.GetClipboardData.restype = ctypes.c_void_p

    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL

    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND

    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int

    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int

    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.GetCursorPos.restype = wintypes.BOOL

    _user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    _user32.SetCursorPos.restype = wintypes.BOOL

    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int

    _user32.BlockInput.argtypes = [wintypes.BOOL]
    _user32.BlockInput.restype = wintypes.BOOL

    _user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
    _user32.SendInput.restype = ctypes.c_uint

    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE

    _kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = ctypes.c_void_p
    _kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalUnlock.restype = ctypes.c_bool
    _kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    _kernel32.GlobalFree.restype = ctypes.c_void_p

    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def enable_dpi_awareness() -> None:
    if not IS_WINDOWS:
        return

    try:
        user32 = USER32
        shcore = ctypes.WinDLL("shcore", use_last_error=True)
        try:
            user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
            return
        except Exception:
            pass

        try:
            shcore.SetProcessDpiAwareness(2)
            return
        except Exception:
            pass

        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass
    except Exception:
        pass


def signal_existing_instance_panel() -> bool:
    if not IS_WINDOWS:
        return False

    _EVENT_MODIFY_STATE = 0x0002
    _SYNCHRONIZE = 0x00100000
    _INSTANCE_PANEL_EVENT_NAME = r"Local\PLatexClient_ShowControlPanel"

    handle = KERNEL32.OpenEventW(_EVENT_MODIFY_STATE | _SYNCHRONIZE, False, _INSTANCE_PANEL_EVENT_NAME)
    if not handle:
        return False

    try:
        return bool(KERNEL32.SetEvent(handle))
    finally:
        KERNEL32.CloseHandle(handle)


_INSTANCE_LOCK_HANDLE = None


def acquire_single_instance_lock() -> bool:
    global _INSTANCE_LOCK_HANDLE
    if not IS_WINDOWS:
        return True

    try:
        KERNEL32.SetLastError(0)
        mutex = KERNEL32.CreateMutexW(None, True, "PLatexClient_SingleInstance")
        err = ctypes.get_last_error()
        if err == 183:
            return False
        _INSTANCE_LOCK_HANDLE = mutex
        return True
    except Exception:
        return False


def release_single_instance_lock() -> None:
    global _INSTANCE_LOCK_HANDLE
    if _INSTANCE_LOCK_HANDLE is None:
        return

    handle = _INSTANCE_LOCK_HANDLE
    _INSTANCE_LOCK_HANDLE = None
    try:
        if IS_WINDOWS:
            KERNEL32.CloseHandle(handle)
    except Exception:
        pass


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" tray'
    if sys.platform == "win32":
        exe = Path(sys.executable)
        if exe.name.lower() == "python.exe":
            pythonw = exe.with_name("pythonw.exe")
            if pythonw.exists():
                return f'"{pythonw}" -m platex_client.cli tray'
    return f'"{sys.executable}" -m platex_client.cli tray'


def is_startup_enabled() -> bool:
    if not IS_WINDOWS:
        return False

    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "PLatexClient"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, app_name)
            return isinstance(value, str) and bool(value.strip())
    except (FileNotFoundError, OSError):
        return False


def set_startup_enabled(enabled: bool) -> None:
    if not IS_WINDOWS:
        return

    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "PLatexClient"
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
