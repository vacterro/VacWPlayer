import os
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
def find_ahk_exe():
    for p in AHK_EXE_CANDIDATES:
        if os.path.isfile(p):
            return p
    import shutil
    return shutil.which("AutoHotkey.exe") or shutil.which("AutoHotkeyU64.exe")

def generate_and_run(config):
    """Write wr_runtime.ahk and (re)launch it. Returns (ok, message)."""
    exe = find_ahk_exe()
    if not exe:
        return False, "AutoHotkey not found - place AutoHotkeyU64.exe next to the app"

    # Validate before generation
    config_warnings = validate_config(config)

    try:
        script, dropped = generate_script(config)
        with open(AHK_PATH, "w", encoding="utf-8") as f:
            f.write(script)
    except (OSError, UnicodeEncodeError) as e:
        return False, "Failed to write AHK script: %s" % e

    # Post-generation scan: catch hotkey collisions invisible to
    # validate_config (fixed generated hotkeys live outside config).
    config_warnings = config_warnings + check_hotkey_conflicts(script)

    # Kill any old instance before launching new one
    stop_ahk()

    try:
        proc = subprocess.Popen([exe, AHK_PATH, str(os.getpid())])
    except (OSError, subprocess.SubprocessError) as e:
        return False, "Failed to launch AutoHotkey: %s" % e

    # Runtime writes its own PID to .ahk.pid on start - nothing to do here.
    # (No Python-side write: a dead pid file must not shadow a failed launch.)

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


_last_scan_ts = 0.0
def _find_our_pids():
    """Return list of PIDs of AutoHotkey processes running our script.

    PowerShell/WMI fallback - expensive (~1s), so throttled to once per
    10s. With the runtime writing its own .ahk.pid this path is only hit
    during startup or after a failed launch.
    """
    global _last_scan_ts
    now = time.monotonic()
    if now - _last_scan_ts < 10:
        return []
    _last_scan_ts = now
    ours = []
    script_abs = os.path.abspath(AHK_PATH).replace("\\", "\\\\")
    ps_cmd = (
        "Get-CimInstance Win32_Process -Filter \"name like '%AutoHotkey%'\" | "
        "Where-Object {{ `$_.CommandLine -like '*{script}*' }} | "
        "Select-Object -ExpandProperty ProcessId"
    ).format(script=script_abs)
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_cmd],
            capture_output=True, creationflags=0x08000000,
            timeout=10).stdout.decode("utf-8", errors="replace")
        for line in out.splitlines():
            line = line.strip()
            if line.isdigit():
                ours.append(int(line))
    except Exception:
        pass
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
    """Check if our managed AHK runtime is still alive."""
    if os.path.isfile(PID_PATH):
        try:
            with open(PID_PATH) as f:
                pid = int(f.read().strip())
            if _pid_alive(pid):
                return True
        except (ValueError, OSError):
            pass

    pids = _find_our_pids()
    if pids:
        try:
            with open(PID_PATH, "w") as f:
                f.write(str(pids[0]))
        except OSError as e:
            print(f"ahk_generator: failed to write recovered PID: {e}", file=sys.stderr)
        return True
    return False

def stop_ahk():
    """Kill our managed runtime by PID + any orphaned instances."""
    tracked = None
    if os.path.isfile(PID_PATH):
        try:
            with open(PID_PATH) as f:
                tracked = int(f.read().strip())
        except Exception as e:
            print(f"ahk_generator: failed to read PID file during stop: {e}", file=sys.stderr)
    orphans = [p for p in _find_our_pids() if p != tracked]
    _stop_pids([tracked] if tracked else [])
    _stop_pids(orphans)
    try:
        os.remove(PID_PATH)
    except OSError:
        pass  # PID file already gone
