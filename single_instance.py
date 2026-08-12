import logging
import os
import subprocess
import sys
import threading
import time

import win32api
import win32con
import win32event
import win32process
import winerror

logger = logging.getLogger(__name__)


def set_timer_resolution(period_ms=1):
    """Raise the Windows timer resolution for the lifetime of the process.

    The default Windows sleep quantum is ~15.6ms, so time.sleep() at a
    sub-16ms poll interval (e.g. 0.030) is quantized and lands erratically
    (0/15.6/31.2/46.8...). timeBeginPeriod(1) drops the quantum to 1ms, which
    is what makes short poll sleeps actually track the configured interval.
    Restored with timeEndPeriod at process exit (atexit). Any failure is
    ignored: a locked-down host that refuses the call simply keeps the coarse
    timer and still polls correctly, just less precisely.
    """
    try:
        import atexit
        import ctypes
        winmm = ctypes.WinDLL("winmm", use_last_error=True)
        if winmm.timeBeginPeriod(period_ms) == 0:
            atexit.register(winmm.timeEndPeriod, period_ms)
    except Exception as e:
        logger.debug("timeBeginPeriod(%d) unavailable: %s", period_ms, e)

def _running_pids():
    try:
        return win32process.EnumProcesses()
    except Exception as e:
        logger.warning("EnumProcesses failed: %s", e)
        return []


def _process_names():
    """All running process image names (lowercase base names) - pure win32, no subprocess spawn."""
    names = set()
    for pid in _running_pids():
        try:
            handle = win32api.OpenProcess(
                win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ,
                False, pid)
        except Exception as e:
            logger.debug("OpenProcess(%d) failed: %s", pid, e)
            continue
        try:
            path = win32process.GetModuleFileNameEx(handle, 0)
            if path:
                names.add(os.path.basename(path).lower())
        except Exception as e:
            logger.debug("GetModuleFileNameEx(%d) failed: %s", pid, e)
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


def _watchdog_state(grace_ticks=2, min_uptime_sec=15.0):
    return {
        "seen_alive": False,
        "pending_ticks": 0,
        "grace_ticks": grace_ticks,
        "min_uptime_sec": min_uptime_sec,
        "fired": False,
    }


def _watchdog_tick(state, tick, alive):
    """One watchdog transition; pure so the trigger logic is testable.

    Returns "alive" | "wait" | "fire". Semantics (T-143):
    - any alive observation establishes seen_alive immediately - a target that
      ran for 5s then died still shuts the assistant down;
    - min_uptime_sec is absence-grace ONLY: after the target was seen, absence
      is ignored until `tick` has reached min_uptime_sec (emulator may be
      restarting), then pending_ticks accumulate and "fire" lands after
      grace_ticks consecutive gone checks.
    """
    if alive:
        state["seen_alive"] = True
        state["pending_ticks"] = 0
        return "alive"
    if not state["seen_alive"]:
        return "wait"  # never saw the target - absence is not "disappeared"
    if tick < state["min_uptime_sec"]:
        return "wait"  # absence-grace window
    state["pending_ticks"] += 1
    if state["pending_ticks"] >= state["grace_ticks"]:
        return "fire"
    return "wait"


def start_target_watchdog(exe_names, on_gone, interval_sec=3.0, grace_ticks=2,
                          min_uptime_sec=15.0, hard_exit_timeout_sec=5.0):
    """Exit the assistant once the target emulator was seen running and then died.

    `exe_names` - iterable of emulator executable names (e.g. HD-Player.exe).
    `on_gone`   - callback invoked (from a daemon thread) when the target goes away.
    `grace_ticks` - consecutive gone-checks required before firing (jitter guard).
    `min_uptime_sec` - absence-grace window: a target that never ran is ignored,
    and a target that just went away is given this long before absence counts.
    `hard_exit_timeout_sec` - how long the watchdog waits for `on_gone` (and the
    GUI cleanup it schedules) before forcing os._exit as a fallback.

    The callback OWNS shutdown (T-143): the watchdog invokes it once, then waits
    a bounded cleanup window. The GUI's on_gone schedules quit_app on the Tk
    mainloop and normal exit finishes the job; os._exit only fires if the
    cleanup never ran in time. Only a target that WAS running triggers shutdown
    on disappearance - a session that never saw the emulator is left alone.
    """
    state = _watchdog_state(grace_ticks, min_uptime_sec)

    def _watch():
        tick = 0.0
        while True:
            time.sleep(interval_sec)
            tick += interval_sec
            action = _watchdog_tick(state, tick, _target_any_alive(exe_names))
            if action != "fire":
                continue
            if not state["fired"]:
                state["fired"] = True
                print(f"target {exe_names} gone - shutting down assistant")
                try:
                    on_gone()
                except Exception as e:
                    logger.warning("on_gone failed: %s", e)
            # bounded cleanup opportunity, then hard exit fallback (T-143)
            time.sleep(hard_exit_timeout_sec)
            os._exit(0)

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return t


_handles = []  # kept alive for the process lifetime; Windows won't let the
               # mutex go stale even on a hard crash, unlike a PID lock file
LOCK_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".locks")


def _pid_file(name):
    return os.path.join(LOCK_DIR, f"{name}.pid")


# Map of single-instance name -> the script it runs. Identity proof for a
# holder pid: its command line must reference this script, distinguishing our
# engine from any unrelated process (e.g. python.exe) that reused the pid.
_NAME_TO_SCRIPT = {
    "accept": "accept.py",
    "surrender": "surrender.py",
    "autocontinue": "autocontinue.py",
    "deathwatch": "deathwatch.py",
    "wr_assistant": "main.pyw",
}


def _split_command_line(cmd):
    """Split a Windows command line into tokens, honoring double-quote quoting
    (cmd.exe-style). `"C:\\Program Files\\app\\accept.py"` is ONE token, and a
    path containing spaces never splits mid-way. `""` inside quotes is a
    literal quote."""
    tokens = []
    cur = []
    in_quotes = False
    i = 0
    while i < len(cmd):
        ch = cmd[i]
        if ch == '"':
            if in_quotes and i + 1 < len(cmd) and cmd[i + 1] == '"':
                cur.append('"')
                i += 2
                continue
            in_quotes = not in_quotes
        elif ch in " \t" and not in_quotes:
            if cur:
                tokens.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
        i += 1
    if cur:
        tokens.append("".join(cur))
    return tokens


def _expected_script_path(script):
    """The absolute path of the script this single-instance name launches.
    ProcessRunner launches engines from this exact absolute path, so the same
    invariant is the only acceptable identity proof for a destructive kill."""
    return os.path.normcase(os.path.abspath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), script)))


def _script_matches(token, script):
    """Exact-token identity for a script path token (T-144/T-158): the token's
    normalized ABSOLUTE path must equal the expected absolute path of the
    script our instance launches. Basename equality is diagnostic evidence at
    most, never destructive proof - a same-named script in another directory
    (C:\\Other\\accept.py) must not be killable as ours. Returns False whenever
    identity cannot be proven."""
    if not isinstance(token, str):
        return False
    norm = token.strip()
    if len(norm) >= 2 and norm.startswith('"') and norm.endswith('"'):
        norm = norm[1:-1]
    norm = norm.strip()
    if not norm:
        return False
    if norm.lower() in ("-m", "--module"):
        return False  # a python -m <name> arg is not a script path
    base = os.path.basename(norm.replace("/", "\\")).lower()
    if base != script.lower():
        return False  # fast reject on basename mismatch
    try:
        actual = os.path.normcase(os.path.abspath(norm))
    except Exception:
        return False
    return actual == _expected_script_path(script)


def _pid_runs_our_script(pid, name):
    """Command-line identity probe: True only when `pid`'s process command
    line carries the script this single-instance name launches, matched as an
    EXACT command-line token (T-144) - substring agreement is not identity.
    Windows PIDs get reused, so an alive PID behind a stale pid file is never
    proof of identity by itself; this probe is what distinguishes ours from
    theirs, and a pid we cannot prove is never killed."""
    script = _NAME_TO_SCRIPT.get(name)
    if script is None:
        return False
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"ProcessId = %d\" | "
             "Select-Object -ExpandProperty CommandLine" % pid],
            capture_output=True, timeout=10,
            creationflags=0x08000000).stdout.decode("utf-8", errors="replace")
    except Exception:
        return False
    return any(_script_matches(t, script)
               for t in _split_command_line(out))


def _write_pid(name):
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        with open(_pid_file(name), "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass


def _kill_previous_holder(name, timeout_sec=5):
    """Best-effort: terminate whatever process wrote the pid file for `name`
    and wait for it to actually exit (so the mutex it holds is released).

    The pid file is only a hint - a live PID behind it is killed only when a
    command-line probe proves it runs OUR script. A stale reused PID pointing
    at an unrelated process is never terminated (T-088)."""
    path = _pid_file(name)
    if not os.path.isfile(path):
        return
    try:
        pid = int(open(path).read().strip())
    except (ValueError, OSError):
        return
    if not _pid_runs_our_script(pid, name):
        print(f"single_instance: refusing to kill pid {pid} for '{name}': "
              f"process identity not proven", file=sys.stderr)
        return
    try:
        # T-185: open the handle with query rights first.
        handle = win32api.OpenProcess(
            win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE |
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return  # can't open - already gone or permission denied
    try:
        # Verify the process instance we just opened is STILL python.exe/pythonw.exe
        # running our script (a reused PID now pointing at notepad.exe fails this).
        import win32process
        img = win32process.GetModuleFileNameEx(handle, 0)
        if not img or not os.path.basename(img).lower().startswith("python"):
            return  # identity changed before open, foreign process
        win32api.TerminateProcess(handle, 0)
        win32event.WaitForSingleObject(handle, int(timeout_sec * 1000))
    except Exception:
        pass
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
    set_timer_resolution()
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
