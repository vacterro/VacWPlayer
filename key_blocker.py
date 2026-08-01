import ctypes
import ctypes.wintypes as wintypes
import threading
import time

WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_KEYUP = 0x0101
WM_SYSKEYUP = 0x0105

VK_MAP = {
    "F13": 0x7C, "F14": 0x7D, "F15": 0x7E, "F16": 0x7F,
    "F17": 0x80, "F18": 0x81, "F19": 0x82, "F20": 0x83,
    "F21": 0x84, "F22": 0x85, "F23": 0x86, "F24": 0x87,
}

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WM_QUIT = 0x0012


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


_LowLevelKeyboardProc = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

user32.CallNextHookEx.restype = ctypes.c_long
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, _LowLevelKeyboardProc, wintypes.HINSTANCE, wintypes.DWORD]
user32.GetMessageW.restype = ctypes.c_int
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, ctypes.c_uint, ctypes.c_uint]
kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
user32.UnhookWindowsHookEx.restype = ctypes.c_long
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.PostThreadMessageW.restype = ctypes.c_long
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM]

_block_until = 0.0
_blocked_vk = set()
_hook_handle = None
_thread = None


def _hook_proc(nCode, wParam, lParam):
    if nCode == 0 and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
        kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        if kb.vkCode in _blocked_vk and time.time() < _block_until:
            return 1  # non-zero = swallow: never reaches the hook chain below
            # us (wr.ahk's own hotkey hook included), nor the focused app.
    return user32.CallNextHookEx(None, nCode, wParam, lParam)


_hook_proc_ref = _LowLevelKeyboardProc(_hook_proc)  # must outlive the hook


def _pump():
    global _hook_handle
    _hook_handle = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _hook_proc_ref, kernel32.GetModuleHandleW(None), 0)
    if not _hook_handle:
        print(f"key_blocker: SetWindowsHookExW failed (error {ctypes.get_last_error()}), "
              f"key blocking will not work")
        return
    msg = wintypes.MSG()
    while True:
        ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if ret == 0:
            break
        if ret == -1:
            import time
            print(f"key_blocker: GetMessageW failed (error {ctypes.get_last_error()})")
            time.sleep(1)
            continue
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def start(blocked_keys=None):
    """Install the low-level keyboard hook with user-configurable blocked keys on a dedicated thread with its own
    message loop (WH_KEYBOARD_LL callbacks only fire while the installing
    thread is pumping messages). Cheap to leave running: outside a block
    window the callback does one timestamp comparison and passes everything
    through via CallNextHookExW.

    Windows calls the most-recently-installed low-level hook first, so as
    long as this starts after wr.ahk is already running (the normal case -
    wr.ahk is the long-running script, deathwatch gets started/restarted
     per session) this intercepts configured keys before wr.ahk's own hotkey hook
    ever sees them.
    """
    global _thread, _blocked_vk
    if _thread is not None:
        return
    if blocked_keys:
        _blocked_vk = {VK_MAP[k] for k in blocked_keys if k in VK_MAP}
    else:
        _blocked_vk = set()
    _thread = threading.Thread(target=_pump, daemon=True)
    _thread.start()
    names = ", ".join(sorted(blocked_keys or []))
    for _ in range(50):  # ~1s: confirm install succeeded before returning
        if _hook_handle:
            print(f"key_blocker: blocking {names}")
            return
        if not _thread.is_alive():
            break
        time.sleep(0.02)
    if not _hook_handle:
        print("key_blocker: hook did not confirm installed within 1s")


def block_pedals_for(seconds):
    """Swallow configured blocked keys for the next `seconds`. wr.ahk's MasterSpammer
    timer keeps firing ability-key spam for as long as a pedal is physically
    held, with no idea a death just happened - if the foot's still down from
    a pre-death combo this stops that spam from competing with quick-buy
    during the window right after death."""
    global _block_until
    _block_until = time.time() + seconds


def unblock():
    """Immediately stop blocking."""
    global _block_until
    _block_until = 0.0



def stop():
    """Remove the hook and stop the message-pump thread."""
    global _hook_handle, _thread
    if _hook_handle:
        user32.UnhookWindowsHookEx(_hook_handle)
        _hook_handle = None
    if _thread and _thread.is_alive():
        tid = _thread.ident
        if tid:
            user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
        _thread.join(timeout=2.0)
        _thread = None
