import json
import os
import subprocess
import sys
import time
import hashlib

import pywintypes
import win32api
import win32con
import win32event
import win32process
from ahk_builder import generate_script, check_hotkey_conflicts
import config_store
from single_instance import _split_command_line

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
# T-184: scan ATTEMPT time (throttle gate) is separate from the time of the
# last SUCCESSFUL identity scan. A failed scan must never refresh the age of
# verified data - only a successful scan updates _last_verified_ts.
_last_scan_ts = 0.0          # last scan ATTEMPT (throttle gate)
_last_verified_ts = 0.0      # when the last SUCCESSFUL identity scan ran
_last_scan_pids = []         # pids verified by that successful scan


# T-W2-PERF-003: cached launched process handle for cheap liveness.
_last_launched_proc = None


def _reset_scan_cache():
    """Force the next is_running()/stop_ahk() to do a fresh scan. Called when
    the runtime world changes (launch, stop) so a cached pre-change result is
    never mistaken for the current one."""
    global _last_scan_ts, _last_verified_ts, _last_scan_pids
    _last_scan_ts = 0.0
    _last_verified_ts = 0.0
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


# T-W2-PERF-007: hash of the last successfully launched script. If a new
# Apply produces the exact same hash AND the runtime is VERIFIED alive, skip
# the full replacement transaction and return Running (unchanged).
_last_launched_script_hash = None


def _script_hash(script):
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


def generate_and_run(config):
    """Transactionally replace the live AHK runtime.

    Flow: render the candidate IN MEMORY -> reject fatally on generation or
    parse errors -> reject fatally on same-context hotkey duplicates -> best-
    effort AHK preflight on a temp copy -> only then atomically replace the
    script, stop the old runtime, launch the candidate. A rejected candidate
    never stops, kills or clobbers the last-good runtime.
    """
    global _last_launched_proc, _last_launched_script_hash
    exe = find_ahk_exe()
    if not exe:
        return False, "AutoHotkey not found - place AutoHotkeyU64.exe next to the app"

    # T-CORE-008: canonical config_store validation gates ALL AHK side effects.
    # Builder diagnostics stay advisory (warnings) and are separate from the
    # hard fail gate so a known-invalid config never reaches codegen/runtime.
    config_problems = config_store.validate_config(config)
    if config_problems:
        return False, "Config rejected: " + "; ".join(config_problems[:3])

    config_warnings = None

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

    # T-W2-PERF-007: if the candidate script hash matches the last successfully
    # launched hash AND the runtime is verified alive, skip the full replacement
    # transaction. Failed candidates never update the trusted hash.
    script_hash = _script_hash(script)
    if (script_hash == _last_launched_script_hash
            and is_running() is True):
        return True, "Running (unchanged)"

    # Best-effort syntax/preflight of the candidate where the binary is
    # available. Tooling absence never blocks the chain (safety net, not the
    # only gate); a real AHK load error does.
    ok, preflight_err = _preflight_script(exe, script)
    if not ok:
        return False, "AHK rejected candidate: %s" % preflight_err

    # Commit point: atomic script replace, then stop the old runtime, then
    # launch the candidate. Order is fixed - the old runtime stays up until
    # the new script file is fully on disk.
    # T-189: snapshot the previous script bytes first so a candidate LAUNCH
    # failure can restore the last-good script instead of leaving it dead.
    prev_script = None
    try:
        with open(AHK_PATH, "rb") as f:
            prev_script = f.read()
    except OSError:
        prev_script = None  # no previous script to restore

    try:
        _atomic_write_script(script)
    except (OSError, UnicodeEncodeError) as e:
        return False, "Failed to write AHK script: %s" % e

    stop_res = stop_ahk()
    if stop_res == "UNKNOWN_IDENTITY":
        # T-190: we could not verify the previous owner is gone - launching
        # another runtime on top of an unknown owner can only double the
        # process count. Abort and restore the previous script state.
        _restore_previous_script(prev_script)
        _reset_scan_cache()
        return False, "AHK restart aborted: previous runtime identity unknown"
    if stop_res == "KILL_FAILED":
        # T-CORE-003: a live managed runtime survived a failed stop - abort
        # replacement to avoid duplicating the automation.
        _restore_previous_script(prev_script)
        _reset_scan_cache()
        return False, "AHK restart aborted: previous runtime kill failed"

    try:
        proc = subprocess.Popen([exe, AHK_PATH, str(os.getpid())])
    except (OSError, subprocess.SubprocessError) as e:
        # T-189: the candidate passed every gate but failed to launch after
        # the old runtime was stopped. Restore the last-good script and
        # best-effort relaunch it so the runtime is not silently dead.
        _restore_previous_script(prev_script)
        _reset_scan_cache()
        if prev_script is not None:
            try:
                old_proc = subprocess.Popen([exe, AHK_PATH, str(os.getpid())])
                return False, ("Failed to launch candidate; last-good runtime "
                               "relaunched (PID %d): %s" % (old_proc.pid, e))
            except Exception as e2:
                return False, ("Failed to launch candidate AND last-good "
                               "relaunch failed: %s / %s" % (e, e2))
        return False, "Failed to launch AutoHotkey: %s" % e

    # Runtime writes its own PID to .ahk.pid on start - nothing to do here.
    # (No Python-side write: a dead pid file must not shadow a failed launch.)
    # The world changed: any cached scan result from before the launch is stale,
    # so the next liveness check scans fresh instead of trusting it.
    _reset_scan_cache()
    # T-W2-PERF-003: cache the launched handle for cheap liveness checks so
    # normal watchdog ticks never need a PowerShell spawn.
    _last_launched_proc = proc
    # T-W2-PERF-007: record the hash of the successfully launched script.
    _last_launched_script_hash = script_hash

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


def _restore_previous_script(prev_bytes):
    """T-189: atomically restore the previous script bytes (None = nothing to
    restore). Used when a replacement that already committed fails to launch."""
    if prev_bytes is None:
        return
    tmp = AHK_PATH + ".restore"
    with open(tmp, "wb") as f:
        f.write(prev_bytes)
    os.replace(tmp, AHK_PATH)


def _inject_preflight_timer(probe):
    """PERF-001: place the self-exit SetTimer INSIDE AHK's auto-execute section.

    AHK v1 only arms a SetTimer if the command executes before the first
    label/hotkey boundary. The old code inserted it immediately AFTER the first
    label's colon (i.e. past that boundary), so the timer was never armed and the
    probe always ran until the 1.5 s communicate timeout and was force-killed.
    Inserting it BEFORE the first label lets the probe self-exit at ~600 ms.
    """
    import re
    lines = probe.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"^[A-Za-z_]\w*:\s*$", line.strip()):
            lines.insert(i, "SetTimer, _WRA_PreflightExit, -600")
            return "\n".join(lines)
    # No label found (degenerate probe): append so it still self-terminates.
    return probe + "\nSetTimer, _WRA_PreflightExit, -600\n"


def _preflight_script(exe, script):
    """Best-effort AHK load-time check of a candidate on a temp copy.

    Returns (ok, diagnostic): ok True when the probe parses, and also when
    preflight is unavailable (missing binary, mocked env, spawn error) - it is
    a safety net, never the only gate. AutoHotkey v1 validates a script before
    entering its message loop; with /ErrorStdOut a load error exits non-zero
    with the message on stdout. The probe self-terminates via a watchdog timer
    so a parsing script never lingers.

    T-W2-PERF-002: the SetTimer for _WRA_PreflightExit is injected BEFORE the
    first generated label so it is armed during the auto-execute section (the
    timer must be set before any label/endsection boundaries, otherwise AHK
    v1 will not arm it for the normal persistent script path). The handler
    itself is appended at the end as before.
    """
    import tempfile
    probe = script
    probe = probe.replace("global ParentPID := %1%", "global ParentPID := 0")
    probe = probe.replace("FileDelete, %A_ScriptDir%\\.ahk.pid",
                          "; preflight: pid-file write disabled")
    probe = probe.replace("FileAppend, %ahkPid%, %A_ScriptDir%\\.ahk.pid",
                          "; preflight: pid-file write disabled")
    # PERF-001: inject the self-exit timer BEFORE the first generated label so AHK
    # v1 arms it during the auto-execute section, instead of after the label's
    # colon (past the boundary) where it was never armed.
    probe = _inject_preflight_timer(probe)
    probe += "_WRA_PreflightExit:\nExitApp\n"
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


def _cmdline_launches_our_script(cmdline):
    """Exact-token ownership (T-181): AutoHotkey's script argument is the FIRST
    command-line token that looks like a script path; that token's normalized
    ABSOLUTE path must equal AHK_PATH exactly. A substring/regex occurrence of
    our path anywhere in the command line is discovery only - it never
    authorizes a kill. Shares the single_instance command-line philosophy."""
    expected = os.path.normcase(os.path.abspath(AHK_PATH))
    try:
        tokens = _split_command_line(cmdline)
    except Exception:
        return False
    for tok in tokens:
        t = tok.strip()
        low = t.lower()
        if low.endswith(".ahk") or low.endswith(".ahk.exe"):
            try:
                return os.path.normcase(os.path.abspath(t)) == expected
            except Exception:
                return False
    return False


def _probe_entries(ps_cmd):
    """Run the PowerShell probe once; return [(pid, command_line), ...] for
    every AutoHotkey process. Command lines are matched in Python by exact
    token, not inside PowerShell by substring regex (T-181).

    Returns ("failed", []) on nonzero return code, malformed non-empty output,
    or invalid schema - callers must never convert a scan failure into an
    authoritative empty result (T-CORE-002).
    """
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_cmd],
        capture_output=True, creationflags=0x08000000,
        timeout=10)
    if result.returncode != 0:
        return "failed", []
    out = result.stdout.decode("utf-8", errors="replace").strip()
    if not out:
        return "ok", []
    try:
        data = json.loads(out)
    except ValueError:
        return "failed", []
    if not data:
        return "ok", []
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return "failed", []
    entries = []
    for item in data:
        if not isinstance(item, dict):
            return "failed", []
        pid = item.get("ProcessId")
        cmd = item.get("CommandLine")
        # T-CORE-002: every item must have an integer (non-bool) ProcessId
        # and a string CommandLine. A dict with invalid fields is a malformed
        # observation - the ENTIRE probe is FAILED, never partially accepted.
        if not isinstance(pid, int) or isinstance(pid, bool):
            return "failed", []
        if not isinstance(cmd, str):
            return "failed", []
        entries.append((pid, cmd))
    return "ok", entries


def _pid_cmdline(pid):
    """Command line of a single PID, or None on failure (T-CORE-001 / CORE-001).

    Used to re-verify a pinned handle's identity: we read the PID from the
    handle and query THAT instance, so a reused PID cannot swap in a foreign
    command line between the handle open and this probe.
    """
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"ProcessId = %d\" | "
        "Select-Object ProcessId, CommandLine | "
        "ConvertTo-Json -Compress" % int(pid)
    )
    try:
        state, entries = _probe_entries(ps_cmd)
    except Exception:
        return None
    if state != "ok" or not entries:
        return None
    if len(entries) != 1 or entries[0][0] != int(pid):
        return None
    return entries[0][1]


def _handle_ownership(h):
    """Tri-state ownership of a pinned process handle (CORE-013).

    Returns 'owned'   - the pinned instance runs OUR script
             'foreign' - PROVEN to be a different process: the image is not an
                         AutoHotkey binary, or it is an AutoHotkey whose command
                         line is not ours. Windows cannot reuse a live PID, so a
                         proven-foreign occupant means the previously-scanned
                         owned instance has already exited.
             'unknown' - ownership could not be proven either way (probe
                         failure); callers must fail closed.
    """
    try:
        img = win32process.GetModuleFileNameEx(h, 0)
    except Exception:
        return "unknown"
    if not img or os.path.basename(img).lower() not in AHK_IMAGE_NAMES:
        return "foreign"
    try:
        pid = win32process.GetProcessId(h)
    except Exception:
        return "unknown"
    cmd = _pid_cmdline(pid)
    if cmd is None:
        return "unknown"
    if _cmdline_launches_our_script(cmd):
        return "owned"
    return "foreign"


def _handle_is_our_ahk(h):
    """Boolean ownership proof for the pinned handle (CORE-013).

    The old code only checked that the opened instance was SOME AutoHotkey
    binary. A PID reused by a foreign AHK script would pass that image check
    and get killed. Here we read the PID from the handle and re-run the
    command-line probe on THAT instance; a reused PID fails the script check
    and is never terminated.
    """
    return _handle_ownership(h) == "owned"


def _find_our_pids(force=False):
    """Return (state, pids) where pids are command-line VERIFIED: only AHK
    processes whose command line carries our script path as the exact first
    script argument (T-181 - exact-token, not substring regex).

    state:
      'ok'      - a fresh scan ran (pids may be empty = verified zero)
      'cached'  - throttled; pids reuse the last verified scan result
      'failed'  - scan error; pids empty (unknown, NOT verified zero)

    A throttled skip is never converted into an authoritative empty list, so
    callers can never read "not scanned" as "not running". A FAILED scan never
    touches the verified timestamp/data (T-184).
    """
    global _last_scan_ts, _last_verified_ts, _last_scan_pids
    now = time.monotonic()
    if not force and now - _last_scan_ts < SCAN_THROTTLE_SEC:
        return "cached", list(_last_scan_pids)
    _last_scan_ts = now  # attempt clock only; failure must not age verified data
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"name like '%AutoHotkey%'\" | "
        "Select-Object ProcessId, CommandLine | "
        "ConvertTo-Json -Compress"
    )
    try:
        state, entries = _probe_entries(ps_cmd)
    except subprocess.TimeoutExpired:
        print("ahk_generator: PID scan timed out (10s), retrying once", file=sys.stderr)
        try:
            state, entries = _probe_entries(ps_cmd)
        except subprocess.TimeoutExpired:
            print("ahk_generator: PID scan timed out again, giving up", file=sys.stderr)
            return "failed", []
        except Exception as e:
            print(f"ahk_generator: PID scan failed: {e}", file=sys.stderr)
            return "failed", []
        if state == "failed":
            return "failed", []
    except Exception as e:
        print(f"ahk_generator: PID scan failed: {e}", file=sys.stderr)
        return "failed", []
    if state == "failed":
        return "failed", []
    pids = [pid for pid, cmd in entries
            if _cmdline_launches_our_script(cmd)]
    # Only a SUCCESSFUL scan promotes verified time/data (T-184).
    _last_verified_ts = time.monotonic()
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
    """Force-kill PIDs and wait briefly for exit.

    T-182: the PID verified by the scan may be REUSED by Windows before we act.
    Every PID is opened as a PROCESS HANDLE and THIS INSTANCE is re-verified as
    an AHK binary immediately before the destructive call - a reused PID now
    pointing at a foreign process is never terminated. All termination happens
    through the handle, never by stale PID number.

    T-CORE-001: every verified PID counts toward the result. OpenProcess
    access-denied (cannot prove exit), TerminateProcess failure, WAIT_TIMEOUT
    (still active), wait error, or still-active after wait is KILL_FAILED.
    Only proof of exit (exit code != STILL_ACTIVE after wait) is success.
    Handles are kept open through proof of exit so the process instance is
    pinned. Returns "STOPPED" when all targeted owned instances are proven
    exited, "KILL_FAILED" when any could not be terminated or proven exited,
    or None when there were no pids to stop.
    """
    if not pids:
        return None
    failed = False
    for pid in pids:
        try:
            h = win32api.OpenProcess(
                win32con.PROCESS_TERMINATE | win32con.SYNCHRONIZE
                | win32con.PROCESS_QUERY_LIMITED_INFORMATION,
                False, pid)
        except pywintypes.error:
            # Cannot open: may be gone (success) or access denied (KILL_FAILED).
            # Since we verified this is our AHK script, access denied is a real
            # failure - we cannot prove exit and must not pretend we did.
            try:
                h_check = win32api.OpenProcess(
                    win32con.PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
                code = win32process.GetExitCodeProcess(h_check)
                win32api.CloseHandle(h_check)
                if code != 259:  # already exited -> success
                    continue
            except Exception:
                pass
            # Cannot determine exit status -> KILL_FAILED
            failed = True
            continue
        try:
            # CORE-013: tri-state ownership of the pinned instance.
            own = _handle_ownership(h)
            if own == "foreign":
                # PROVEN foreign occupant on a reused PID: the original scanned
                # owned instance is already gone (Windows reuses a PID only
                # after it exits). Leave the foreign process untouched and
                # count this target complete - not a failure to stop the old
                # owned runtime.
                win32api.CloseHandle(h)
                continue
            if own == "unknown":
                # Cannot prove ours NOR foreign: cannot prove the original is
                # gone. Fail closed - never terminate on an unverifiable
                # identity, and never report a clean stop on an unproven one.
                win32api.CloseHandle(h)
                failed = True
                continue
        except pywintypes.error:
            win32api.CloseHandle(h)
            failed = True
            continue
        try:
            win32api.TerminateProcess(h, 0)
        except pywintypes.error as e:
            print(f"ahk_generator: terminate pid failed: {e}")
            failed = True
            try:
                win32api.CloseHandle(h)
            except Exception:
                pass
            continue
        # Wait BEFORE closing so we can prove exit; keep handle open through wait.
        try:
            rc = win32event.WaitForSingleObject(h, max(0, int(wait_ms)))
            if rc != 0:  # WAIT_OBJECT_0 = proven exited; WAIT_TIMEOUT or error = KILL_FAILED
                failed = True
                print(f"ahk_generator: wait for exit returned rc={rc:#x}")
        except pywintypes.error:
            failed = True
        try:
            win32api.CloseHandle(h)
        except Exception:
            pass
    return "KILL_FAILED" if failed else "STOPPED"


def _force_kill_ahk_processes(pids):
    """Nuclear fallback: taskkill /F for PIDs that survived TerminateProcess.
    Only called on VERIFIED PIDs. Returns True if all targets confirmed dead."""
    all_dead = True
    for pid in pids:
        if not _pid_alive(pid):
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True, creationflags=0x08000000, timeout=5)
        except Exception:
            pass
        time.sleep(0.2)
        if _pid_alive(pid):
            all_dead = False
    return all_dead


def is_running():
    """True / False / None (UNKNOWN).

    True when our managed AHK runtime is VERIFIED alive. The PID file is only
    a hint (Windows reuses PIDs): a live process behind the file counts as
    ours only when a command-line scan proved it runs our script. The cheap
    path reuses the last VERIFIED result only while its OWN verified TTL is
    valid (T-184) - a failed scan never extends that age. None means the
    identity state is genuinely unknown (verified cache expired AND no fresh
    scan could run): callers must not treat UNKNOWN as either stopped or
    running.

    T-W2-PERF-003: if we have a trusted launched handle whose process is still
    alive (poll() is None), AND the launched PID is in our verified set or the
    launched handle's pid was used for the last verified scan, return True
    without any spawn.

    T-CORE-003: the fast-path launched handle also checks that the PID matches
    the tracked set - a PID reused by a foreign process between the handle's
    poll() and our cache would otherwise pass.
    """
    global _last_launched_proc
    # PERF-002 / T-W2-PERF-003: the retained Popen handle IS the exact process
    # instance VacWPlayer launched (subprocess.Popen pins the real child). A live
    # handle cannot be "reused" out from under us by Windows, so an alive handle
    # is authoritative liveness for OUR runtime - no second scan needed. This is
    # the fast path that lets an identical Apply return "Running (unchanged)"
    # without spawning PowerShell/CIM. Command-line discovery is reserved for when
    # the trusted handle is absent/dead (orphan recovery, GUI restart).
    if _last_launched_proc is not None:
        try:
            if _last_launched_proc.poll() is None:
                return True
        except Exception:
            pass
        # Handle is dead or gone - drop it so the full path can rescan.
        _last_launched_proc = None
    pid = _read_pidfile()
    now = time.monotonic()
    if pid is not None and _last_scan_pids and now - _last_verified_ts < VERIFIED_WINDOW_SEC:
        if pid in _last_scan_pids and _pid_is_ahk_image(pid):
            return True
    state, pids = _find_our_pids(force=False)
    if state in ("failed", "cached"):
        if now - _last_verified_ts < VERIFIED_WINDOW_SEC:
            return bool(_last_scan_pids)
        return None
    return bool(pids)


def stop_ahk():
    """Kill our managed runtime by VERIFIED identity only.

    The PID file is a hint: a tracked PID is killed only when a fresh forced
    command-line scan proves it runs our script. A stale reused PID belonging
    to an unrelated process never matches the scan and is never terminated.

    Returns one of:
      'STOPPED'          - verified our runtime(s), terminated, evidence cleared
      'ALREADY_STOPPED'  - fresh scan verified zero of our processes
      'UNKNOWN_IDENTITY' - identity scan failed; ownership evidence is RETAINED
                           (PID file + verified cache), nothing was claimed
      'KILL_FAILED'      - verified process could not be terminated

    T-183: on UNKNOWN_IDENTITY the PID file and verified cache are NOT erased -
    the runtime may still be alive and the application must not pretend to have
    stopped it, nor launch a replacement as if zero were proven.
    """
    global _last_scan_pids, _last_launched_proc, _last_launched_script_hash
    tracked = _read_pidfile()
    state, pids = _find_our_pids(force=True)
    if state == "failed":
        # Scan unavailable: we cannot prove ownership of anything. Keep the
        # PID file and verified cache as the only tracking evidence.
        print("ahk_generator: stop aborted - identity scan failed (UNKNOWN)", file=sys.stderr)
        return "UNKNOWN_IDENTITY"
    if tracked is not None and tracked not in pids:
        tracked = None
    orphans = [p for p in pids if p != tracked]
    # T-CORE-001: combine tracked+orphan results. Both must succeed for the
    # entire stop to be considered successful. KILL_FAILED means at least one
    # verified target could not be proven exited.
    tracked_result = _stop_pids([tracked] if tracked else [])
    orphan_result = _stop_pids(orphans)
    if tracked_result == "KILL_FAILED" or orphan_result == "KILL_FAILED":
        # Escalation: taskkill /F fallback for hung processes
        all_pids = ([tracked] if tracked else []) + orphans
        if _force_kill_ahk_processes(all_pids):
            # Escalation succeeded — clean up evidence
            print("ahk_generator: taskkill escalation succeeded", file=sys.stderr)
            try:
                os.remove(PID_PATH)
            except OSError:
                pass
            _last_scan_pids = []
            _last_launched_proc = None
            _last_launched_script_hash = None
            return "STOPPED"
        # Ownership evidence is RETAINED: PID file, verified cache, and
        # launched handle are NOT cleared so a failed stop cannot erase
        # ownership while a live runtime remains.
        print("ahk_generator: kill failed even after taskkill escalation", file=sys.stderr)
        return "KILL_FAILED"
    try:
        os.remove(PID_PATH)
    except OSError:
        pass  # PID file already gone
    _last_scan_pids = []
    # T-W2-PERF-003: drop the cached handle on stop/restart so the next
    # liveness check uses a fresh source of truth.
    _last_launched_proc = None
    _last_launched_script_hash = None
    return "ALREADY_STOPPED" if not pids else "STOPPED"


def cleanup_stale_before_start():
    """Pre-launch cleanup: kill any orphaned wr_runtime.ahk from previous session.
    Called once at app startup before the first apply_and_start()."""
    state, pids = _find_our_pids(force=True)
    if state == "failed" or not pids:
        return
    print("ahk_generator: killing %d orphaned runtime(s) from previous session"
          % len(pids), file=sys.stderr)
    result = _stop_pids(pids)
    if result == "KILL_FAILED":
        _force_kill_ahk_processes(pids)
    try:
        os.remove(PID_PATH)
    except OSError:
        pass
    _reset_scan_cache()


def cleanup_temp_ahk_files():
    """Remove orphaned tmp*.ahk preflight probe files from project dir."""
    import glob
    removed = 0
    for f in glob.glob(os.path.join(BASE, "tmp*.ahk")):
        try:
            os.remove(f)
            removed += 1
        except OSError:
            pass
    if removed:
        print("ahk_generator: cleaned up %d orphaned tmp*.ahk files" % removed,
              file=sys.stderr)
