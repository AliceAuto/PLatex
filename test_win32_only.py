from platex_client.win32_hotkey import Win32HotkeyListener
import time
import ctypes

print("=== Test 1: Basic hotkey registration ===")
l = Win32HotkeyListener()

def on_hotkey():
    print(f"HOTKEY FIRED at {time.time():.3f}!")

# Register a hotkey
result = l.register("Ctrl+Shift+E", on_hotkey)
print(f"register result: {result}")
print(f"_callbacks: {l._callbacks}")
print(f"_hotkey_to_id: {l._hotkey_to_id}")

# Start the listener
l.start()
print(f"Started: {l._thread is not None and l._thread.is_alive()}")
time.sleep(0.5)

# Simulate WM_HOTKEY from the message loop thread
if l._thread and l._thread.is_alive():
    tid = l._thread.ident
    print(f"Thread ID: {tid}")
    # Send WM_HOTKEY with wparam=1 (the hotkey id)
    result = ctypes.windll.user32.PostThreadMessageW(tid, 0x0312, 1, 0)
    print(f"PostThreadMessageW result: {result}, err: {ctypes.windll.kernel32.GetLastError()}")
    time.sleep(0.5)

l.stop()
print("Stopped")