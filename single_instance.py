import os
import sys
import threading
import time

import win32api
import win32con
import win32event
import win32process
import winerror

def _running_pids():
    try:
        return win32process.EnumProcesses()
    except Exception:
        return []


def _process_names():
    """All running process image names (lowercase base names) - pure win32, no subprocess spawn."""
    names = set()
    for pid in _running_pids():
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ,
                False, pid)
        except Exception:
            continue
        try:
            path = win32process.GetModuleFileNameEx(handle, 0)
            if path:
                names.add(os.path.basename(path).lower())
        except Exception:
            pass
        finally:
            win32api.CloseHandle(handle)
    return names


def _target_any_alive(exe_names):
    """True when at least one of the given executable names is running."""
    if not exe_names:
        return True
    lower = {n.lower() for n in exe_names if n}
    if not lower:
        return True
    return bool(lower & _process_names())


def _parent_alive(pid):
    """Pure win32 liveness probe for a parent PID - no subprocess spawns."""
    if pid <= 0:
        return False
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return False
    try:
        # STATUS_PROCESS_IS_TERMINATING / invalid handle both mean gone.
        # STILL_ACTIVE = 259 (winerror has no STILL_ACTIVE attribute).
        code = win32process.GetExitCodeProcess(handle)
        return code == 259
    except Exception:
        return False
    finally:
        win32api.CloseHandle(handle)


def start_parent_watchdog(interval_sec=2.0):
    """Exit when the process that spawned us dies.

    Engines are children of the GUI: if the GUI is killed or crashes, an
    orphaned engine would keep holding its single-instance mutex and keep
    firing clicks into BlueStacks. This watchdog makes the engine follow
    its parent into death, so a fresh GUI launch always gets a clean set
    of engines - one instance, always.
    """
    parent = os.getppid()

    def _watch():
        while True:
            time.sleep(interval_sec)
            if not _parent_alive(parent):
                print(f"parent {parent} gone - exiting")
                os._exit(0)

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return t


def start_target_watchdog(exe_names, on_gone, interval_sec=3.0, grace_ticks=2, min_uptime_sec=15.0):
    """Exit the assistant once the target emulator was seen running and then died.

    `exe_names` - iterable of emulator executable names (e.g. HD-Player.exe).
    `on_gone`   - callback invoked (from a daemon thread) when the target goes away.
    `grace_ticks` - consecutive gone-checks required before firing (jitter guard).
    `min_uptime_sec` - ignore the very first seconds: the GUI may start before
    BlueStacks, and a not-yet-started emulator must not count as "disappeared".

    Only a target that WAS running triggers shutdown on disappearance - a
    session that never saw BlueStacks (user launched the assistant alone) is
    left alone.
    """
    seen_alive = False
    pending_ticks = 0
    state = {}

    def _watch():
        nonlocal seen_alive, pending_ticks
        tick = 0.0
        while True:
            time.sleep(interval_sec)
            tick += interval_sec
            alive = _target_any_alive(exe_names)
            if alive:
                seen_alive = tick >= min_uptime_sec or seen_alive
                pending_ticks = 0
                state["alive"] = True
                continue
            if not seen_alive:
                continue
            pending_ticks += 1
            state["gone"] = pending_ticks
            if pending_ticks >= grace_ticks:
                print(f"target {exe_names} gone - shutting down assistant")
                try:
                    on_gone()
                finally:
                    os._exit(0)

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return t


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
    err = win32api.GetLastError()
    # ERROR_ACCESS_DENIED means the name exists but we may not open it -
    # still "someone else holds the lock", treat it as busy either way.
    already_running = err in (winerror.ERROR_ALREADY_EXISTS, winerror.ERROR_ACCESS_DENIED)
    _handles.append(handle)

    if already_running and replace:
        if handle in _handles:
            _handles.remove(handle)
        win32api.CloseHandle(handle)
        _kill_previous_holder(name)
        handle = win32event.CreateMutex(None, False, mutex_name)
        err = win32api.GetLastError()
        already_running = err in (winerror.ERROR_ALREADY_EXISTS, winerror.ERROR_ACCESS_DENIED)
        _handles.append(handle)

    if already_running:
        print(f"another '{name}' instance is already running - exiting")
        sys.exit(1)

    _write_pid(name)
