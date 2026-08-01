import os
import sys

import win32api
import win32con
import win32event
import winerror

_handles = []  # kept alive for the process lifetime; Windows won't let the
               # mutex go stale even on a hard crash, unlike a PID lock file
LOCK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".locks")


def _pid_file(name):
    return os.path.join(LOCK_DIR, f"{name}.pid")


def _write_pid(name):
    os.makedirs(LOCK_DIR, exist_ok=True)
    with open(_pid_file(name), "w") as f:
        f.write(str(os.getpid()))


def _kill_previous_holder(name, timeout_sec=5):
    """Best-effort: terminate whatever process wrote the pid file for `name`
    and wait for it to actually exit (so the mutex it holds is released)."""
    path = _pid_file(name)
    if not os.path.isfile(path):
        return
    try:
        pid = int(open(path).read().strip())
    except (ValueError, OSError):
        return
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE, False, pid)
    except Exception:
        return  # can't open — already gone or permission denied
    try:
        win32api.TerminateProcess(handle, 0)
        win32event.WaitForSingleObject(handle, int(timeout_sec * 1000))
    finally:
        win32api.CloseHandle(handle)


def ensure_single_instance(name, replace=False):
    """Exit immediately if another process already holds this name's lock -
    unless replace=True, in which case that other process is killed first
    and this one takes its place.

    Call once at the very start of main(). Running two copies of the same
    watcher against the same BlueStacks window is actively harmful, not just
    wasteful - both would fire quick-buy/minimize/click on the same event,
    doubling key presses and racing each other's minimize/restore calls.

    replace=True force-terminates the previous holder (TerminateProcess, no
    graceful shutdown) - fine for "I edited settings, apply them now" from
    the GUI, but if it lands mid quick-buy-burst or mid-click a key/button
    could in theory stay logically "down" for the fraction of a second that
    was in flight. Plain command-line launches default to replace=False so
    an accidental double-launch just refuses instead of silently killing
    something.
    """
    mutex_name = f"WildRiftTool_{name}"
    handle = win32event.CreateMutex(None, False, mutex_name)
    already_running = win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
    _handles.append(handle)

    if already_running and replace:
        if handle in _handles:
            _handles.remove(handle)
        win32api.CloseHandle(handle)
        _kill_previous_holder(name)
        handle = win32event.CreateMutex(None, False, mutex_name)
        already_running = win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
        _handles.append(handle)

    if already_running:
        print(f"another '{name}' instance is already running - exiting")
        sys.exit(1)

    _write_pid(name)
