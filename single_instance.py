import contextlib
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

    T-W2-PERF-006: this was called from ensure_single_instance(), which runs
    for EVERY engine process (GUI, accept, surrender, autocontinue, deathwatch).
    Now removed from the shared path; each engine calls it only when it needs
    sub-16ms precision (DeathWatch quick-buy).
    """
    try:
        import atexit
        import ctypes
        winmm = ctypes.WinDLL("winmm", use_last_error=True)
        if winmm.timeBeginPeriod(period_ms) == 0:
            atexit.register(winmm.timeEndPeriod, period_ms)
    except Exception as e:
        logger.debug("timeBeginPeriod(%d) unavailable: %s", period_ms, e)


@contextlib.contextmanager
def timer_resolution(period_ms=1):
    """T-W2-PERF-007: scope fine-grained timer resolution to a short critical
    section and restore the coarse default on exit - GUARANTEED, even on
    exception.

    Replaces the old process-lifetime set_timer_resolution() so the OS sleep
    quantum is only dropped to ~1ms while a timing-sensitive input burst
    (DeathWatch quick-buy) is actually happening, then handed back. Every other
    engine tolerates the default ~15.6ms quantum just fine."""
    winmm = None
    try:
        import ctypes
        winmm = ctypes.WinDLL("winmm", use_last_error=True)
        if winmm.timeBeginPeriod(period_ms) != 0:
            winmm = None  # request rejected -> stay coarse, don't pretend
    except Exception as e:
        logger.debug("timeBeginPeriod(%d) unavailable: %s", period_ms, e)
        winmm = None
    try:
        yield
    finally:
        if winmm is not None:
            try:
                winmm.timeEndPeriod(period_ms)
            except Exception:
                pass


def _running_pids():
    try:
        return win32process.EnumProcesses()
    except Exception as e:
        logger.warning("EnumProcesses failed: %s", e)
        return None  # UNKNOWN: cannot determine


def _image_name(pid):
    """Lowercased base image name for one PID, or None if unobservable.

    PERF-001: factored out of the full-table scan so target-early-exit can
    open only the PIDs it needs and return on the first proven match."""
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ,
            False, pid)
    except Exception as e:
        logger.debug("OpenProcess(%d) failed: %s", pid, e)
        return None
    try:
        path = win32process.GetModuleFileNameEx(handle, 0)
        return os.path.basename(path).lower() if path else None
    except Exception as e:
        logger.debug("GetModuleFileNameEx(%d) failed: %s", pid, e)
        return None
    finally:
        win32api.CloseHandle(handle)


def _target_any_alive(exe_names):
    """True / False / None (UNKNOWN).

    CORE-004: an incomplete scan (some PID unobservable) can never prove the
    target absent - return None. Only a fully-observed no-match returns False.
    PERF-001: the target-name test is merged into the PID scan with an
    early-exit on the first proven match - no full-table name-set build in the
    healthy already-seen-alive case.
    """
    if not exe_names:
        return True
    lower = {n.lower() for n in exe_names if n}
    if not lower:
        return True
    pids = _running_pids()
    if pids is None:
        return None
    complete = True
    for pid in pids:
        name = _image_name(pid)
        if name is None:
            complete = False
            continue
        if name in lower:
            return True  # PERF-001: early-exit on first proven match
    if not complete:
        return None  # CORE-004: partial observation cannot prove absence
    return False


def _parent_alive(pid):
    """Pure win32 liveness probe for a parent PID - no subprocess spawns.

    T-CORE-013: returns None (UNKNOWN) on observation failure instead of
    False, so a transient probe error does not feed orphan shutdown.
    """
    if pid <= 0:
        return False
    try:
        handle = win32api.OpenProcess(win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return None
    try:
        code = win32process.GetExitCodeProcess(handle)
        return code == 259
    except Exception:
        return None
    finally:
        win32api.CloseHandle(handle)


def start_parent_watchdog(interval_sec=2.0):
    """Exit when the process that spawned us dies.

    Engines are children of the GUI: if the GUI is killed or crashes, an
    orphaned engine would keep holding its single-instance mutex and keep
    firing clicks into BlueStacks. This watchdog makes the engine follow
    its parent into death, so a fresh GUI launch always gets a clean set
    of engines - one instance, always.

    T-CORE-009: opens a SYNCHRONIZE handle to the original parent once at
    startup and monitors that same process instance until signaled. A
    recycled PID never fools the watchdog into thinking the original parent
    is still alive. The handle is released on watcher termination.
    """
    parent = os.getppid()
    # Open a handle to the original parent once. We monitor THIS instance,
    # not a PID number that Windows can recycle.
    parent_handle = None
    try:
        parent_handle = win32api.OpenProcess(
            win32con.SYNCHRONIZE | win32con.PROCESS_QUERY_LIMITED_INFORMATION,
            False, parent)
    except Exception:
        pass  # parent already gone or inaccessible

    def _watch():
        if parent_handle is not None:
            try:
                # PERF-006: block on the pinned handle until the original parent
                # signals exit. No periodic polling/wakeups - the waitable handle
                # is the signal, PID reuse is irrelevant because the instance is
                # pinned. WAIT_OBJECT_0 means the original parent exited.
                rc = win32event.WaitForSingleObject(parent_handle,
                                                    win32event.INFINITE)
                if rc != 0:
                    # INFINITE cannot time out; a non-zero rc is a wait error.
                    # Fall through to the bounded fail-closed retry rather than
                    # treating an unpinned wait as "parent alive forever".
                    raise RuntimeError(f"parent wait rc={rc:#x}")
                print(f"parent {parent} gone - exiting")
                os._exit(0)
            except Exception:
                pass
            finally:
                try:
                    win32api.CloseHandle(parent_handle)
                except Exception:
                    pass
        # Handle never opened, or the wait errored: parent is either already
        # gone or inaccessible. One bounded retry; the retry result decides.
        try:
            handle = win32api.OpenProcess(
                win32con.SYNCHRONIZE | win32con.PROCESS_QUERY_LIMITED_INFORMATION,
                False, parent)
            rc = win32event.WaitForSingleObject(handle, win32event.INFINITE)
            win32api.CloseHandle(handle)
            if rc == 0:
                print(f"parent {parent} gone - exiting")
                os._exit(0)
            # rc != 0: the retry wait could not resolve the parent either.
            # Fail closed - an engine that cannot verify its parent must not
            # keep running unowned.
            print(f"parent {parent} gone (wait unresolved) - exiting")
            os._exit(0)
        except Exception:
            pass
        print(f"parent {parent} gone (handle unavailable) - exiting")
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
    - None (UNKNOWN) observation leaves counters unchanged - transient
      probe failures never feed forced shutdown (T-CORE-013).
    """
    if alive is None:
        return "wait"  # UNKNOWN: do not alter state
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


class _WatchdogHandle:
    """Ownership handle for a running target watchdog (W2-002).

    `stop()` invalidates this generation: the loop notices and exits before
    the next observation, and a pending hard-exit fallback is cancelled so a
    superseded watcher can never shut the app down after replacement."""

    def __init__(self):
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    @property
    def stopped(self):
        return self._stop_event.is_set()


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

    Returns a `_WatchdogHandle`. `handle.stop()` invalidates this generation
    (W2-002): the owner may cancel/retarget on config change; a cancelled
    watcher neither observes, fires, nor hard-exits after replacement.

    The callback OWNS shutdown (T-143): the watchdog invokes it once, then waits
    a bounded cleanup window. The GUI's on_gone schedules quit_app on the Tk
    mainloop and normal exit finishes the job; os._exit only fires if the
    cleanup never ran in time. Only a target that WAS running triggers shutdown
    on disappearance - a session that never saw the emulator is left alone.
    """
    state = _watchdog_state(grace_ticks, min_uptime_sec)
    handle = _WatchdogHandle()

    def _watch():
        tick = 0.0
        while not handle.stopped:
            time.sleep(interval_sec)
            if handle.stopped:
                return
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
            # bounded cleanup opportunity, then hard exit fallback (T-143).
            # If the watcher was cancelled during the window, abort the
            # fallback - a superseded generation must never os._exit.
            time.sleep(hard_exit_timeout_sec)
            if handle.stopped:
                return
            os._exit(0)

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    handle._thread = t
    return handle


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


def _handle_is_our_script(handle, pid, name):
    """Authoritative ownership proof for the PINNED handle we are about to
    terminate (T-CORE-004 / CORE-001).

    The old code proved ownership by PID *before* opening the handle, then
    only re-checked the interpreter image after opening - a textbook TOCTOU:
    a PID verified as ours can be recycled by Windows between the probe and
    OpenProcess, so the handle we terminate belongs to a foreign process that
    merely shares the interpreter image.

    Here we verify the handle's OWN instance: (1) its image is an interpreter
    we launch, and (2) its command line carries our exact script path. We read
    the PID from the handle and re-run the command-line probe on THAT instance.
    Because the open handle pins the specific process object, GetProcessId and
    the command-line query always resolve to the same instance - a reused PID
    (foreign process) fails the script check and is never killed.
    """
    try:
        img = win32process.GetModuleFileNameEx(handle, 0)
    except Exception:
        return False
    if not img:
        return False
    base = os.path.basename(img).lower()
    if base not in ("python.exe", "pythonw.exe", "autohotkeyu64.exe",
                    "autohotkey.exe"):
        return False  # not an interpreter we launch - refuse to kill
    try:
        real_pid = win32process.GetProcessId(handle)
    except Exception:
        return False
    # The handle pins this instance, so real_pid and the command-line query
    # below always describe the SAME process - no reuse window.
    return _pid_runs_our_script(real_pid, name)


def _write_pid(name):
    try:
        os.makedirs(LOCK_DIR, exist_ok=True)
        with open(_pid_file(name), "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        return False
    return True


def _kill_previous_holder(name, timeout_sec=5):
    """Best-effort: terminate whatever process wrote the pid file for `name`
    and wait for it to actually exit (so the mutex it holds is released).

    The pid file is only a hint - a live PID behind it is killed only when a
    command-line probe proves it runs OUR script. A stale reused PID pointing
    at an unrelated process is never terminated (T-088).

    T-CORE-004 / CORE-001: the handle is opened FIRST and kept pinned through
    the ownership proof and the destructive decision. Ownership is re-verified
    against THAT handle's own instance (see _handle_is_our_script) - we never
    reopen a fresh handle or treat interpreter image equality as ownership.
    """
    path = _pid_file(name)
    if not os.path.isfile(path):
        return
    try:
        pid = int(open(path).read().strip())
    except (ValueError, OSError):
        return
    try:
        # Open the handle FIRST and retain it through proof + terminate + wait.
        # We do NOT prove-by-PID-then-open: that window is the TOCTOU where a
        # reused PID swaps in a foreign process between proof and OpenProcess.
        handle = win32api.OpenProcess(
            win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE |
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except Exception:
        return  # can't open - already gone or permission denied
    try:
        # Re-verify ownership against the handle we are about to terminate.
        # A PID reused by a foreign process fails this check (wrong command
        # line) and is never killed.
        if not _handle_is_our_script(handle, pid, name):
            print(f"single_instance: refusing to kill pid {pid} for '{name}': "
                  f"process identity not proven", file=sys.stderr)
            return
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
    # T-W2-PERF-007: timer resolution is NO LONGER requested here (process
    # lifetime). It is scoped to the quick-buy input burst in
    # window_ctl.press_key_burst via single_instance.timer_resolution().
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

    # W2-006: the mutex is authoritative but the pid file is the replacement
    # hint (`_kill_previous_holder` reads it). If the holder metadata cannot
    # be published, release the just-acquired mutex and fail startup visibly
    # BEFORE any runtime side effects - a mutex-holder that can never be
    # replaced by replace=True is a trap, not a lock.
    if not _write_pid(name):
        if handle in _handles:
            _handles.remove(handle)
        try:
            win32api.CloseHandle(handle)
        except Exception:
            pass
        raise RuntimeError(
            f"single_instance: failed to write pid file for '{name}' - "
            f"cannot publish holder identity; refusing to start")
