import ctypes
import sys
import time

import win32gui
import win32con
import win32api
import win32process



def set_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception as e:
        print(f"window_ctl: SetProcessDPIAware failed: {e}", file=sys.stderr)
        pass


def minimize(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)


def maximize_and_focus(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    _force_foreground(hwnd)


def switch_to(hwnd):
    """Bring an already-open window to the front for the death window, without
    forcing its size - unlike BlueStacks (always maximized), a work window
    (editor, browser, etc.) should reappear at whatever size/position it was
    left at, just un-minimized if needed."""
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    _force_foreground(hwnd)


def _force_foreground(hwnd):
    try:
        win32gui.SetForegroundWindow(hwnd)
        return
    except Exception as e:
        print(f"window_ctl: simple SetForegroundWindow failed: {e}", file=sys.stderr)
        pass
    # Windows blocks foreground-steal from background processes unless the
    # caller was the last to have an input event. Borrowing input state from
    # whatever currently owns the foreground satisfies that check without
    # broadcasting a real keypress that could land on an unrelated window
    # (e.g. an Alt keydown/keyup sent system-wide can graze other apps).
    fg_hwnd = win32gui.GetForegroundWindow()
    current_thread_id = win32api.GetCurrentThreadId()
    fg_thread_id = win32process.GetWindowThreadProcessId(fg_hwnd)[0] if fg_hwnd else 0
    attached = False
    try:
        if fg_thread_id and fg_thread_id != current_thread_id:
            win32process.AttachThreadInput(current_thread_id, fg_thread_id, True)
            attached = True
        win32gui.SetForegroundWindow(hwnd)
    finally:
        if attached:
            win32process.AttachThreadInput(current_thread_id, fg_thread_id, False)


def click_at(hwnd, x, y, button="right"):
    """Click a point given in client coordinates. Sends background window
    messages (like ControlClick) without moving the real OS cursor.
    """
    lparam = win32api.MAKELONG(x, y)
    
    if button == "left":
        down = win32con.WM_LBUTTONDOWN
        up = win32con.WM_LBUTTONUP
        wparam = win32con.MK_LBUTTON
    else:
        down = win32con.WM_RBUTTONDOWN
        up = win32con.WM_RBUTTONUP
        wparam = win32con.MK_RBUTTON

    win32gui.PostMessage(hwnd, down, wparam, lparam)
    time.sleep(0.05)
    win32gui.PostMessage(hwnd, up, 0, lparam)



def release_mouse_buttons(hwnd):
    """Post plain button-up messages to `hwnd` without touching real input.

    wr_runtime.ahk holds RButton down for as long as the movement remap is
    engaged. When a death minimizes the window mid-hold, AHK's own release
    fires into a window that is no longer active and the game keeps walking.
    PostMessage still reaches a minimized window and, unlike mouse_event, it
    generates no hardware event - so it neither trips BlueStacks' cursor
    capture nor lands in whatever app the death switched to.

    Best effort by design: an emulator that ignores synthetic messages simply
    stays as it was, and wr_runtime.ahk's NeedCleanup burst covers it on the
    way back in.
    """
    lparam = win32api.MAKELONG(0, 0)
    for msg in (win32con.WM_LBUTTONUP, win32con.WM_RBUTTONUP,
                win32con.WM_MBUTTONUP):
        try:
            win32gui.PostMessage(hwnd, msg, 0, lparam)
        except Exception as e:
            print(f"window_ctl: release_mouse_buttons failed: {e}",
                  file=sys.stderr)
            return


def key_vk(letter):
    """Windows virtual-key code for a single letter key (A-Z map directly to
    their uppercase ASCII value)."""
    return ord(letter.upper())


def press_key_burst(hwnd, vk_code, times=5, window_ms=150):
    """Send `times` real keydown/keyup presses spread across window_ms total.

    Keyboard input has no coordinate to target like a click does - it always
    goes to whichever window currently has keyboard focus. Sending it blind
    risks it landing somewhere else entirely (a chat box, another app) if
    BlueStacks isn't actually focused right now, so this refuses to fire in
    that case rather than spam keys into whatever's in front.
    """
    if win32gui.GetForegroundWindow() != hwnd:
        return False

    interval = (window_ms / 1000.0) / times
    hold = min(0.005, interval / 2)
    for _ in range(times):
        win32api.keybd_event(vk_code, 0, 0, 0)
        time.sleep(hold)
        win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)
        time.sleep(max(0.0, interval - hold))
    return True
