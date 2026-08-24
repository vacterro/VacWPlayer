import ctypes
import sys
import time

import win32gui
import win32con
import win32api
import win32process

from engine_config import quickbuy_key_vk
import single_instance



def set_dpi_aware():
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception as e:
        print(f"window_ctl: SetProcessDPIAware failed: {e}", file=sys.stderr)
        pass


def minimize(hwnd):
    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)


def maximize_and_focus(hwnd):
    """Best-effort: maximize + focus the game window for the death sequence.
    Never raises - a background watcher must not die over a window-op refusal."""
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
    except Exception as e:
        print(f"window_ctl: ShowWindow failed: {e}", file=sys.stderr)
    try:
        _force_foreground(hwnd)
    except Exception as e:
        print(f"window_ctl: focus failed: {e}", file=sys.stderr)


def switch_to(hwnd):
    """Bring an already-open window to the front for the death window, without
    forcing its size - unlike the game window (always maximized), a work window
    (editor, browser, etc.) should reappear at whatever size/position it was
    left at, just un-minimized if needed. Best-effort, never raises."""
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        _force_foreground(hwnd)
    except Exception as e:
        print(f"window_ctl: switch_to failed: {e}", file=sys.stderr)


def _force_foreground(hwnd):
    """Best-effort focus. Windows refuses foreground-steal from background
    processes (pywintypes.error (0, 'SetForegroundWindow', ...)) unless the
    caller was last to have an input event - this is EXPECTED for a background
    watcher, never a reason to die. Every attempt is guarded and logged;
    the function never raises."""
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
    except Exception as e:
        # Focus steal is best-effort: the game window is already maximized and
        # resurrect actions are gated on GetForegroundWindow() == hwnd, so a
        # refused focus simply skips them - it must NEVER kill the watcher.
        print(f"window_ctl: SetForegroundWindow refused: {e}", file=sys.stderr)
    finally:
        if attached:
            try:
                win32process.AttachThreadInput(current_thread_id, fg_thread_id, False)
            except Exception:
                pass


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
    """Windows virtual-key code for a quickbuy key.

    Consumes the canonical parser (engine_config.quickbuy_key_vk, T-140): a
    single ASCII letter/digit -> its uppercase code point, vkNN hex -> the
    code, anything else -> None. None must never reach keybd_event - configs
    are validated against the same parser before the engine runs.
    """
    return quickbuy_key_vk(letter)


def press_key_burst(hwnd, vk_code, times=5, window_ms=150):
    """Send `times` real keydown/keyup presses spread across window_ms total.

    W2-002: JIT-checks foreground immediately before every DOWN. Once focus
    is lost, all remaining presses are aborted. Tracks whether each DOWN
    succeeded and guarantees its UP in a finally block, even if focus
    changes or an exception occurs during the hold.

    T-W2-PERF-007: the ~5ms holds only track the configured interval when the
    OS sleep quantum is ~1ms. That resolution is scoped to this burst via a
    timer_resolution() context manager and restored the instant the burst ends,
    instead of being held for the whole process lifetime."""
    if win32gui.GetForegroundWindow() != hwnd:
        return False

    interval = (window_ms / 1000.0) / times
    hold = min(0.005, interval / 2)
    sent_count = 0
    with single_instance.timer_resolution(1):
        for i in range(times):
            # W2-002: JIT foreground check immediately before every DOWN.
            if win32gui.GetForegroundWindow() != hwnd:
                break  # abort remaining presses
            down_sent = False
            try:
                win32api.keybd_event(vk_code, 0, 0, 0)
                down_sent = True
                sent_count += 1
                time.sleep(hold)
            finally:
                # W2-002: guarantee UP in finally even if hold/sleep raises.
                if down_sent:
                    try:
                        win32api.keybd_event(vk_code, 0, win32con.KEYEVENTF_KEYUP, 0)
                    except Exception:
                        pass
            time.sleep(max(0.0, interval - hold))
    return sent_count > 0
