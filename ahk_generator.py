import os
import shutil
import subprocess
import sys
from ahk_builder import generate_script, validate_config

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

    # Kill any old instance before launching new one
    stop_ahk()

    try:
        proc = subprocess.Popen([exe, AHK_PATH, str(os.getpid())])
    except (OSError, subprocess.SubprocessError) as e:
        return False, "Failed to launch AutoHotkey: %s" % e

    # Write PID atomically
    pid_path_tmp = PID_PATH + ".tmp"
    try:
        with open(pid_path_tmp, "w") as f:
            f.write(str(proc.pid))
        os.replace(pid_path_tmp, PID_PATH)
    except OSError as e:
        print(f"ahk_generator: PID file race during launch: {e}", file=sys.stderr)

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

def _find_our_pids():
    """Return list of PIDs of AutoHotkey processes running our script."""
    print("WARNING: falling back to PowerShell _find_our_pids()!", flush=True)
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
    except Exception as e:
        print(f"ahk_generator: PowerShell fallback failed: {e}", file=sys.stderr)
    return ours

def _stop_pids(pids, wait_ms=500):
    """Force-kill PIDs and wait briefly for exit."""
    if not pids:
        return
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, creationflags=0x08000000)
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
            r = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/NH"],
                               capture_output=True, creationflags=0x08000000)
            if str(pid) in r.stdout.decode("utf-8", errors="replace"):
                return True
        except Exception as e:
            print(f"ahk_generator: tasklist check failed for cached PID: {e}", file=sys.stderr)
            
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
    except OSError as e:
        print(f"ahk_generator: failed to remove PID file during stop: {e}", file=sys.stderr)
        pass  # PID file already gone
