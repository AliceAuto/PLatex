import subprocess
import time
import ctypes
from ctypes import wintypes
import sys

THREADENTRY32 = ctypes.Structure
class _T(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", ctypes.c_int),
        ("tpDeltaPri", ctypes.c_int), ("dwFlags", wintypes.DWORD),
    ]
THREADENTRY32 = _T

def find_threads(proc_pid):
    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
    k32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
    k32.OpenThread.restype = ctypes.c_void_p
    k32.OpenThread.argtypes = [wintypes.DWORD, ctypes.c_bool, wintypes.DWORD]
    k32.GetThreadDescription.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]

    snap = k32.CreateToolhelp32Snapshot(4, 0)
    if snap == -1:
        return []
    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    result = []
    if k32.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == proc_pid:
                h = k32.OpenThread(0x0004, False, te.th32ThreadID)
                if h:
                    try:
                        ptr = ctypes.c_void_p()
                        if k32.GetThreadDescription(h, ctypes.byref(ptr)) == 0 and ptr.value:
                            name = ctypes.c_wchar_p(ptr.value).value
                            if any(frag in name for frag in ["hotkey", "win32", "message"]):
                                result.append((te.th32ThreadID, name))
                    finally:
                        k32.CloseHandle(h)
            if not k32.Thread32Next(snap, ctypes.byref(te)):
                break
    k32.CloseHandle(snap)
    return result

if __name__ == "__main__":
    proc = subprocess.Popen(
        [sys.executable, "-m", "platex_client.cli", "tray"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    print(f"Started tray, pid={proc.pid}")
    time.sleep(4)

    log = r"C:\Users\27427\AppData\Roaming\PLatexClient\logs\platex-client.log"
    user32 = ctypes.windll.user32
    k32 = ctypes.windll.kernel32

    threads = find_threads(proc.pid)
    print(f"Found threads: {threads}")

    for tid, name in threads:
        print(f"\nTesting thread {tid} ({name}):")
        time.sleep(0.3)
        for hkid in [1, 2, 3]:
            r = user32.PostThreadMessageW(tid, 0x0312, hkid, 0)
            print(f"  PostThreadMessageW(WM_HOTKEY, wparam={hkid}): ret={r}, err={k32.GetLastError()}")
            time.sleep(0.2)

    time.sleep(1)
    try:
        with open(log, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        print("\nLast 20 log lines:")
        for l in lines[-20:]:
            print(" ", l.rstrip())
    except Exception as e:
        print(f"Log error: {e}")

    proc.terminate()
    proc.wait(2)