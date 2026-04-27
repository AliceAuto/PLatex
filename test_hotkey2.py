import subprocess
import time
import ctypes
from ctypes import wintypes
import sys

THREADENTRY32 = ctypes.Structure
class _TH(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("th32ThreadID", wintypes.DWORD),
        ("th32OwnerProcessID", wintypes.DWORD), ("tpBasePri", ctypes.c_int),
        ("tpDeltaPri", ctypes.c_int), ("dwFlags", wintypes.DWORD),
    ]

THREADENTRY32 = _TH

def get_threads_by_name(proc_pid, name_fragments):
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.Thread32First.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
    kernel32.Thread32Next.argtypes = [ctypes.c_void_p, ctypes.POINTER(THREADENTRY32)]
    kernel32.OpenThread.restype = ctypes.c_void_p
    kernel32.OpenThread.argtypes = [wintypes.DWORD, ctypes.c_bool, wintypes.DWORD]
    kernel32.GetThreadDescription.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.GetLastError.restype = wintypes.DWORD

    TH32CS_SNAPTHREAD = 4
    THREAD_QUERY_INFORMATION = 0x0004

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if snap == -1:
        return []

    te = THREADENTRY32()
    te.dwSize = ctypes.sizeof(THREADENTRY32)
    threads = []

    if kernel32.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == proc_pid:
                h = kernel32.OpenThread(THREAD_QUERY_INFORMATION, False, te.th32ThreadID)
                if h:
                    try:
                        desc_ptr = ctypes.c_void_p()
                        res = kernel32.GetThreadDescription(h, ctypes.byref(desc_ptr))
                        if res == 0 and desc_ptr.value:
                            name = ctypes.c_wchar_p(desc_ptr.value).value
                            for frag in name_fragments:
                                if frag in name:
                                    threads.append((te.th32ThreadID, name))
                                    break
                    finally:
                        kernel32.CloseHandle(h)
            if not kernel32.Thread32Next(snap, ctypes.byref(te)):
                break

    kernel32.CloseHandle(snap)
    return threads

if __name__ == "__main__":
    proc = subprocess.Popen(
        [sys.executable, "-m", "platex_client.cli", "tray"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    print(f"Tray started, pid: {proc.pid}")
    time.sleep(3)

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    threads = get_threads_by_name(proc.pid, ["win32-hotkey", "hotkey"])
    print(f"Found hotkey threads: {threads}")

    for tid, name in threads:
        time.sleep(0.2)
        for hkid in [1, 2]:
            result = user32.PostThreadMessageW(tid, 0x0312, hkid, 0)
            print(f"PostThreadMessageW(tid={tid}, WM_HOTKEY, wparam={hkid}): result={result}, err={kernel32.GetLastError()}")
            time.sleep(0.3)

    time.sleep(2)
    log_path = r"C:\Users\27427\AppData\Roaming\PLatexClient\logs\platex-client.log"
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        print("Last 15 log lines:")
        for line in lines[-15:]:
            print(" ", line.rstrip())
    except Exception as e:
        print(f"Could not read log: {e}")

    proc.terminate()
    proc.wait(timeout=2)