import os
import re
import subprocess
import sys
import time

import pywintypes
import win32api
import win32con
import win32process
from ahk_builder import generate_script, validate_config, check_hotkey_conflicts

"""Renders wr_runtime.ahk from config and manages its process.

wr_runtime.ahk is a GENERATED file - never hand-edit it. All input handling
(combo spam, mouse remap, movement) runs in AutoHotkey v1 because emulators
need SendMode Event and AHK's hook layer is proven; Python only writes the
script and owns its lifetime by PID.
"""
BASE = os.path.dirname(os.path.abspath(__file__))
AHK_NAME = "wr_runtime.ahk"
AHK_PATH = os.path.join(BASE, AHK_NAME)
PID_PATH = os.path.join(BASE, ".ahk.pid")
AHK_EXE_CANDIDATES = [
    os.path.join(BASE, "AutoHotkeyU64.exe"),  # bundled portable
    r"C:\Program Files\AutoHotkey\AutoHotkeyU64.exe",
    r"C:\Program Files\AutoHotkey\AutoHotkey.exe",
    r"C:\Program Files (x86)\AutoHotkey\AutoHotkeyU64.exe",
    r"C:\Program Files (x86)\AutoHotkey\AutoHotkey.exe",
]
# Image names of the AHK binaries we launch. A PID whose process image is none
# of these is provably not ours; a match is only a plausibility gate, never
# full identity (Windows reuses PIDs).
AHK_IMAGE_NAMES = {"autohotkeyu64.exe", "autohotkey.exe"}

# A command-line scan spawns PowerShell (~0.5-1s); throttle it. A skipped scan
# is NEVER treated as an authoritative empty result - cached verified pids are
# reused instead, so "not scanned" never reads as "not running".
SCAN_THROTTLE_SEC = 10.0
# How long a command-line-verified pid stays trusted for the cheap is_running()
# fast path (win32 image probe, no spawn). Longer than the scan throttle keeps
# the engine watchdog off the main thread's spawn cost; bounded so a reused
# pid can never be trusted forever.
VERIFIED_WINDOW_SEC = 30.0
_last_scan_ts = 0.0
_last_scan_pids = []


def _reset_scan_cache():
    """Force the next is_running()/stop_ahk() to do a fresh scan. Called when
    the runtime world changes (launch, stop) so a cached pre-change result is
    never mistaken for the current one."""
    global _last_scan_ts, _last_scan_pids
    _last_scan_ts = 0.0
    _last_scan_pids = []


def find_ahk_exe():
    for p in AHK_EXE_CANDIDATES:
        if os.path.isfile(p):
            return p
    import shutil
    return shutil.which("AutoHotkey.exe") or shutil.which("AutoHotkeyU64.exe")


def _read_pidfile():
    """PID file content as int, or None (missing/corrupt). Hint only - a live
    process behind the file is NOT proof it is ours."""
    try:
        with open(PID_PATH) as f:
            return int(f.read().strip())
    except (ValueError, OSError):
        return None


def _pid_is_ahk_image(pid):
    """Cheap win32 plausibility gate: is `pid` alive AND running one of our
    AHK binaries? A reused PID pointing at another AHK script passes this -
    callers must combine it with a command-line identity check before killing
    or reporting the process as ours."""
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION | win32con.PROCESS_VM_READ,
            False, pid)
    except pywintypes.error:
        return False
    try:
        if win32process.GetExitCodeProcess(handle) != 259:  # STILL_ACTIVE
            return False
        img = win32process.GetModuleFileNameEx(handle, 0)
        if not img:
            return False
        return os.path.basename(img).lower() in AHK_IMAGE_NAMES
    except pywintypes.error:
        return False
    except Exception:
        return False
    finally:
        win32api.CloseHandle(handle)


def generate_and_run(config):
    """Transactionally replace the live AHK runtime.

    Flow: render the candidate IN MEMORY -> reject fatally on generation or
    parse errors -> reject fatally on same-context hotkey duplicates -> best-
    effort AHK preflight on a temp copy -> only then atomically replace the
    script, stop the old runtime, launch the candidate. A rejected candidate
    never stops, kills or clobbers the last-good runtime.
    """
    exe = find_ahk_exe()
    if not exe:
        return False, "AutoHotkey not found - place AutoHotkeyU64.exe next to the app"

    config_warnings = validate_config(config)

    # Render in memory first - the live script file is not touched until the
    # candidate has passed every gate below.
    try:
        script, dropped = generate_script(config)
    except ValueError as e:
        return False, "Invalid combo: %s" % e
    except Exception as e:
        return False, "Generation failed: %s" % e

    # Post-generation scan: catch hotkey collisions invisible to
    # validate_config (fixed generated hotkeys live outside config). A
    # same-context duplicate is FATAL - real AHK exits 2 on it, so the
    # candidate could never run. Ordinary config warnings above stay warnings.
    conflicts = check_hotkey_conflicts(script)
    if conflicts:
        return False, "Hotkey conflict: %s" % conflicts[0]

    # Best-effort syntax/preflight of the candidate where the binary is
    # available. Tooling absence never blocks the chain (safety net, not the
    # only gate); a real AHK load error does.
    ok, preflight_err = _preflight_script(exe, script)
    if not ok:
        return False, "AHK rejected candidate: %s" % preflight_err

    # Commit point: atomic script replace, then stop the old runtime, then
    # launch the candidate. Order is fixed - the old runtime stays up until
    # the new script file is fully on disk.
    try:
        _atomic_write_script(script)
    except (OSError, UnicodeEncodeError) as e:
        return False, "Failed to write AHK script: %s" % e

    stop_ahk()

    try:
        proc = subprocess.Popen([exe, AHK_PATH, str(os.getpid())])
    except (OSError, subprocess.SubprocessError) as e:
        return False, "Failed to launch AutoHotkey: %s" % e

    # Runtime writes its own PID to .ahk.pid on start - nothing to do here.
    # (No Python-side write: a dead pid file must not shadow a failed launch.)
    # The world changed: any cached scan result from before the launch is stale,
    # so the next liveness check scans fresh instead of trusting it.
    _reset_scan_cache()

    if config_warnings:
        msg = "Warnings: " + "; ".join(config_warnings[:3])
        if len(config_warnings) > 3:
            msg += " (+%d more)" % (len(config_warnings) - 3)
        if dropped:
            msg += " | dropped: " + ", ".join(dropped)
    else:
        msg = "Running (PID %d)" % proc.pid
        if dropped:
            msg += " - dropped duplicate triggers: " + ", ".join(dropped)
    return True, msg


def _atomic_write_script(script):
    """Write the generated script via temp + os.replace so a crash mid-write
    never leaves a truncated wr_runtime.ahk."""
    tmp = AHK_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(script)
    os.replace(tmp, AHK_PATH)


def _preflight_script(exe, script):
    """Best-effort AHK load-time check of a candidate on a temp copy.

    Returns (ok, diagnostic): ok True when the probe parses, and also when
    preflight is unavailable (missing binary, mocked env, spawn error) - it is
    a safety net, never the only gate. AutoHotkey v1 validates a script before
    entering its message loop; with /ErrorStdOut a load error exits non-zero
    with the message on stdout. The probe self-terminates via a watchdog timer
    so a parsing script never lingers.
    """
    import tempfile
    probe = script
    # The real script's startup reads the parent python pid from %1% and
    # deletes/rewrites .ahk.pid with its own pid. A probe launched without
    # args would hit the blank-%1% error dialog and clobber the live runtime's
    # pid file - neutralize both, then exit on a timer.
    probe = probe.replace("global ParentPID := %1%", "global ParentPID := 0")
    probe = probe.replace("FileDelete, %A_ScriptDir%\\.ahk.pid",
                          "; preflight: pid-file write disabled")
    probe = probe.replace("FileAppend, %ahkPid%, %A_ScriptDir%\\.ahk.pid",
                          "; preflight: pid-file write disabled")
    probe += ("\nSetTimer, _WRA_PreflightExit, -600\n"
              "_WRA_PreflightExit:\n"
              "ExitApp\n")
    try:
        fd, tmp = tempfile.mkstemp(suffix=".ahk", dir=BASE)
    except OSError:
        return True, None
    try:
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(probe)
            proc = subprocess.Popen(
                [exe, "/ErrorStdOut", tmp],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=0x08000000)
        except OSError:
            return True, None  # binary unavailable/mocked: preflight not run
        try:
            out, _ = proc.communicate(timeout=1.5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            return True, None  # still running past the probe window = parses fine
        except Exception:
            return True, None
        if proc.returncode == 0:
            return True, None
        text = (out or b"").decode("utf-8", errors="replace").strip()
        return False, text or ("exit code %d" % proc.returncode)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _pid_alive(pid):
    """True if the process is alive. Pure win32 - no subprocess spawn, so the
    3s engine watchdog costs ~0 CPU instead of spawning tasklist/powershell."""
    try:
        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except pywintypes.error:
        return False
    try:
        return win32process.GetExitCodeProcess(handle) == 259  # STILL_ACTIVE
    except pywintypes.error:
        return False
    finally:
        win32api.CloseHandle(handle)


def _find_our_pids(force=False):
    """Return (state, pids) where pids are command-line VERIFIED: only AHK
    processes whose command line carries our script path.

    state:
      'ok'      - a fresh scan ran (pids may be empty = verified zero)
      'cached'  - throttled; pids reuse the last verified scan result
      'failed'  - scan error; pids empty (unknown, NOT verified zero)

    A throttled skip is never converted into an authoritative empty list, so
    callers can never read "not scanned" as "not running".
    """
    global _last_scan_ts, _last_scan_pids
    now = time.monotonic()
    if not force and now - _last_scan_ts < SCAN_THROTTLE_SEC:
        return "cached", list(_last_scan_pids)
    _last_scan_ts = now
    # Regex (-match) + re.escape: the command line carries the script path with
    # SINGLE backslashes. Two historical traps: the -like wildcard doubled them
    # and never matched, and a backtick before `$_` made PowerShell treat
    # `$_.CommandLine` as a command name instead of the process's command line -
    # both made the scan silently return zero and the engine watchdog restart
    # forever. Plain member access + -match (case-insensitive) works.
    script_esc = re.escape(os.path.abspath(AHK_PATH))
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"name like '%AutoHotkey%'\" | "
        "Where-Object {{ $_.CommandLine -match '{script}' }} | "
        "Select-Object -ExpandProperty ProcessId"
    ).format(script=script_esc)
    try:
        pids = _probe_pids(ps_cmd)
    except subprocess.TimeoutExpired:
        print("ahk_generator: PID scan timed out (10s), retrying once", file=sys.stderr)
        try:
            pids = _probe_pids(ps_cmd)
        except subprocess.TimeoutExpired:
            print("ahk_generator: PID scan timed out again, giving up", file=sys.stderr)
            return "failed", []
        except Exception as e:
            print(f"ahk_generator: PID scan failed: {e}", file=sys.stderr)
            return "failed", []
    except Exception as e:
        print(f"ahk_generator: PID scan failed: {e}", file=sys.stderr)
        return "failed", []
    _last_scan_pids = pids
    return "ok", pids


def _probe_pids(ps_cmd):
    """Run the PowerShell probe once and parse its PID lines."""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, creationflags=0x08000000,
        timeout=10).stdout.decode("utf-8", errors="replace")
    ours = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            ours.append(int(line))
    return ours


def _stop_pids(pids, wait_ms=500):
    """Force-kill PIDs and wait briefly for exit."""
    if not pids:
        return
    for pid in pids:
        r = subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, creationflags=0x08000000)
        if r.returncode != 0:
            print(f"taskkill {pid} failed (code {r.returncode}): {r.stderr.decode().strip()}")
    # Wait briefly for processes to die
    if wait_ms:
        import time
        deadline = time.monotonic() + wait_ms / 1000
        while pids and time.monotonic() < deadline:
            alive = []
            for pid in pids:
                r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                                   capture_output=True, creationflags=0x08000000)
                if str(pid) in r.stdout.decode("utf-8", errors="replace"):
                    alive.append(pid)
            pids = alive
            if pids:
                time.sleep(0.05)


def is_running():
    """True when our managed AHK runtime is VERIFIED alive.

    The PID file is only a hint (Windows reuses PIDs): a live process behind
    the file counts as ours only when a command-line scan proved it runs our
    script - the cheap path reuses the last verified result within the
    throttle window. A skipped scan is never read as "not running".
    """
    pid = _read_pidfile()
    now = time.monotonic()
    if pid is not None and now - _last_scan_ts < VERIFIED_WINDOW_SEC:
        if pid in _last_scan_pids and _pid_is_ahk_image(pid):
            return True
    state, pids = _find_our_pids(force=False)
    if state == "failed" and now - _last_scan_ts < VERIFIED_WINDOW_SEC:
        # Scan unavailable (broken powershell etc.): reuse the last VERIFIED
        # result rather than blind-restarting from a genuinely unknown state.
        return bool(_last_scan_pids)
    return bool(pids)


def stop_ahk():
    """Kill our managed runtime by VERIFIED identity only.

    The PID file is a hint: a tracked PID is killed only when a fresh forced
    command-line scan proves it runs our script. A stale reused PID belonging
    to an unrelated process never matches the scan and is never terminated.
    """
    global _last_scan_pids
    tracked = _read_pidfile()
    state, pids = _find_our_pids(force=True)
    if tracked is not None and tracked not in pids:
        tracked = None
    orphans = [p for p in pids if p != tracked]
    _stop_pids([tracked] if tracked else [])
    _stop_pids(orphans)
    try:
        os.remove(PID_PATH)
    except OSError:
        pass  # PID file already gone
    # Everything we kill came from the verified set; the cache now holds that
    # same set, so a cached-empty read within the throttle window correctly
    # reports stopped.
    _last_scan_pids = []
