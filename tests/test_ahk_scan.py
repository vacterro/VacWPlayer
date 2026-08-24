"""ahk_generator PID-scan tests: silent-except removal (T-032), throttle
vs zero distinction (T-087), PID identity verification (T-088), exact-token
ownership (T-181)."""

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import ahk_generator as ag


class FakeOut:
    def __init__(self, text="", returncode=0):
        self.stdout = text.encode("utf-8")
        self.stderr = b""
        self.returncode = returncode


def _monkey_ts(monkeypatch, value=99.0):
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: value)


def _ours(pid=777):
    """(pid, cmdline) pair launching OUR script exactly (T-181)."""
    return (pid, '"C:\\Python\\AutoHotkeyU64.exe" "%s" 1' % ag.AHK_PATH)


# --- _probe_entries (JSON pid+cmdline) --------------------------------------

def test_probe_entries_parses_json(monkeypatch):
    import json as _j
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return FakeOut(_j.dumps([
            {"ProcessId": 123, "CommandLine": 'x "a.ahk"'},
            {"ProcessId": 456, "CommandLine": "y"},
        ]))

    monkeypatch.setattr(ag.subprocess, "run", fake_run)
    state, entries = ag._probe_entries("CMD")
    assert state == "ok"
    assert entries == [(123, 'x "a.ahk"'), (456, "y")]
    assert "powershell" in calls[0][0]


def test_probe_entries_empty_and_single_object(monkeypatch):
    import json as _j
    monkeypatch.setattr(ag.subprocess, "run", lambda *a, **k: FakeOut(""))
    state, entries = ag._probe_entries("")
    assert state == "ok"
    assert entries == []
    state, entries = ag._probe_entries("")
    assert state == "ok"
    assert entries == []
    monkeypatch.setattr(ag.subprocess, "run",
                        lambda *a, **k: FakeOut(_j.dumps(
                            {"ProcessId": 1, "CommandLine": "x"})))
    state, entries = ag._probe_entries("")
    assert state == "ok"
    assert entries == [(1, "x")]


def test_probe_entries_nonzero_rc_returns_failed(monkeypatch):
    monkeypatch.setattr(ag.subprocess, "run",
                        lambda *a, **k: FakeOut(returncode=1))
    state, entries = ag._probe_entries("CMD")
    assert state == "failed"
    assert entries == []


def test_probe_entries_malformed_json_returns_failed(monkeypatch):
    monkeypatch.setattr(ag.subprocess, "run",
                        lambda *a, **k: FakeOut("not json"))
    state, entries = ag._probe_entries("CMD")
    assert state == "failed"
    assert entries == []


def test_probe_entries_invalid_item_schema_returns_failed(monkeypatch):
    import json as _j
    monkeypatch.setattr(ag.subprocess, "run",
                        lambda *a, **k: FakeOut(_j.dumps(["not-a-dict"])))
    state, entries = ag._probe_entries("CMD")
    assert state == "failed"
    assert entries == []


# --- _find_our_pids (state, pids) contract ---------------------------------

def test_find_our_pids_success(monkeypatch):
    _monkey_ts(monkeypatch)
    monkeypatch.setattr(ag, "_probe_entries", lambda ps_cmd: ("ok", [_ours(777)]))
    state, pids = ag._find_our_pids()
    assert state == "ok"
    assert pids == [777]


def test_find_our_pids_verified_zero(monkeypatch):
    _monkey_ts(monkeypatch)
    monkeypatch.setattr(ag, "_probe_entries", lambda ps_cmd: ("ok", []))
    state, pids = ag._find_our_pids()
    assert state == "ok"
    assert pids == []


def test_find_our_pids_throttle_reuses_cached(monkeypatch):
    _monkey_ts(monkeypatch)
    monkeypatch.setattr(ag, "_probe_entries", lambda ps_cmd: ("ok", [_ours(1)]))
    state, pids = ag._find_our_pids()  # first call runs the scan
    assert state == "ok"
    assert pids == [1]
    # second call inside the throttle window: cache reuse, NOT [] - a skipped
    # scan is never converted into an authoritative zero (T-087).
    state2, pids2 = ag._find_our_pids()
    assert state2 == "cached"
    assert pids2 == [1]


def test_find_our_pids_force_bypasses_throttle(monkeypatch):
    _monkey_ts(monkeypatch)
    calls = []

    def fake(ps_cmd):
        calls.append(1)
        return ("ok", [_ours(42)])

    monkeypatch.setattr(ag, "_probe_entries", fake)
    ag._find_our_pids()
    state, pids = ag._find_our_pids(force=True)
    assert state == "ok"
    assert pids == [42]
    assert len(calls) == 2


def test_find_our_pids_timeout_retries_once(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)
    calls = []

    def flaky(ps_cmd):
        calls.append(1)
        if len(calls) == 1:
            raise subprocess.TimeoutExpired("powershell", 10)
        return ("ok", [_ours(42)])

    monkeypatch.setattr(ag, "_probe_entries", flaky)
    state, pids = ag._find_our_pids()
    assert state == "ok"
    assert pids == [42]
    assert len(calls) == 2
    assert "retrying once" in capsys.readouterr().err


def test_find_our_pids_double_timeout_gives_up(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)
    calls = []

    def always_timeout(ps_cmd):
        calls.append(1)
        raise subprocess.TimeoutExpired("powershell", 10)

    monkeypatch.setattr(ag, "_probe_entries", always_timeout)
    state, pids = ag._find_our_pids()
    assert state == "failed"
    assert pids == []
    assert len(calls) == 2
    assert "timed out again" in capsys.readouterr().err


def test_find_our_pids_other_exception_logs(monkeypatch, capsys):
    _monkey_ts(monkeypatch, value=99.0)

    def boom(ps_cmd):
        raise OSError("powershell missing")

    monkeypatch.setattr(ag, "_probe_entries", boom)
    state, pids = ag._find_our_pids()
    assert state == "failed"
    assert pids == []
    assert "PID scan failed" in capsys.readouterr().err


def test_scan_uses_json_not_substring_regex(monkeypatch):
    """Identity moved to Python exact-token matching (T-181): the PowerShell
    probe fetches ProcessId + CommandLine as JSON - no -match substring regex
    is allowed to authorize anything."""
    captured = {}

    def fake(ps_cmd):
        captured["cmd"] = ps_cmd
        return ("ok", [(123, "x")])

    monkeypatch.setattr(ag, "_probe_entries", fake)
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 99.0)

    ag._find_our_pids(force=True)

    cmd = captured["cmd"]
    assert "-match" not in cmd
    assert "ProcessId" in cmd and "CommandLine" in cmd
    assert "ConvertTo-Json" in cmd


# --- T-087: throttle must not mean "no process" ----------------------------

def test_is_running_reuses_cached_verified_pid(monkeypatch):
    """A cached verified pid behind the pid file reports running WITHOUT a
    rescan - 'not scanned' never reads as 'not running'."""
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 123)
    monkeypatch.setattr(ag, "_last_scan_ts", 5.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 5.1)  # inside 10s window
    monkeypatch.setattr(ag, "_last_scan_pids", [123])
    monkeypatch.setattr(ag, "_pid_is_ahk_image", lambda pid: True)
    scanned = []
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: scanned.append(force) or ("cached", [123]))
    assert ag.is_running() is True
    assert scanned == []  # fast path, no spawn


def test_is_running_cached_zero_after_stop_stays_false(monkeypatch):
    """After stop_ahk the cache is verified-empty: is_running reports stopped
    within the throttle window without rescanning."""
    monkeypatch.setattr(ag, "_read_pidfile", lambda: None)
    monkeypatch.setattr(ag, "_last_scan_ts", 5.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 5.1)
    monkeypatch.setattr(ag, "_last_scan_pids", [])
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("cached", []))
    assert ag.is_running() is False


# --- T-088: PID file is not process identity -------------------------------

def test_is_running_never_reports_unrelated_alive_pid(monkeypatch):
    """A stale pid file whose pid was reused by an unrelated-but-alive process
    must not be reported as ours: it was never command-line verified."""
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 999)
    monkeypatch.setattr(ag, "_last_scan_ts", 5.0)
    monkeypatch.setattr(ag.time, "monotonic", lambda: 5.1)
    monkeypatch.setattr(ag, "_last_scan_pids", [])      # verified: not ours
    monkeypatch.setattr(ag, "_pid_is_ahk_image", lambda pid: True)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("cached", []))
    assert ag.is_running() is False


def test_stop_ahk_kills_only_verified_pids(monkeypatch):
    killed = []
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 111)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("ok", [111, 222]))
    monkeypatch.setattr(ag, "_stop_pids",
                        lambda pids, wait_ms=500: killed.extend(pids))
    monkeypatch.setattr(ag.os, "remove", lambda *a, **k: None)
    ag.stop_ahk()
    assert killed == [111, 222]


def test_stop_ahk_does_not_kill_unrelated_reused_pid(monkeypatch):
    """A tracked pid that the forced scan does NOT verify as ours is never
    killed - the stale reused pid case (T-088 regression)."""
    killed = []
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 999)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("ok", []))  # 999 is NOT ours
    monkeypatch.setattr(ag, "_stop_pids",
                        lambda pids, wait_ms=500: killed.extend(pids))
    monkeypatch.setattr(ag.os, "remove", lambda *a, **k: None)
    ag.stop_ahk()
    assert killed == []


def test_stop_ahk_uses_force_scan(monkeypatch):
    """Explicit stop always scans fresh, even right after a throttled scan
    (T-087): stop immediately after a previous scan still finds orphans."""
    forces = []
    monkeypatch.setattr(ag, "_read_pidfile", lambda: None)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: forces.append(force) or ("ok", [5]))
    monkeypatch.setattr(ag, "_stop_pids", lambda pids, wait_ms=500: None)
    monkeypatch.setattr(ag.os, "remove", lambda *a, **k: None)
    ag.stop_ahk()
    assert forces == [True]

# --- T-182: kill by handle with instance re-verify (TOCTOU) -------------------

def test_stop_pids_kills_only_verified_ahk_instances(monkeypatch):
    killed, closed = [], []
    monkeypatch.setattr(ag.win32api, "OpenProcess",
                        lambda acc, inh, pid: pid)
    monkeypatch.setattr(ag.win32process, "GetModuleFileNameEx",
                        lambda h, i: {101: r"C:\AHK\AutoHotkeyU64.exe",
                                      202: r"C:\WINDOWS\notepad.exe"}[h])
    # CORE-001: ownership is now verified against the pinned handle. Only our
    # AHK script (handle 101) passes; the foreign notepad (202) does not.
    monkeypatch.setattr(ag, "_handle_is_our_ahk", lambda h: h == 101)
    monkeypatch.setattr(ag.win32api, "TerminateProcess",
                        lambda h, c: killed.append(h))
    monkeypatch.setattr(ag.win32api, "CloseHandle", lambda h: closed.append(h))
    monkeypatch.setattr(ag.win32event, "WaitForSingleObject",
                        lambda h, ms: 0)
    ag._stop_pids([101, 202])
    assert killed == [101]   # reused non-AHK pid is NEVER terminated
    assert 202 in closed     # foreign handle is closed, not killed


def test_stop_pids_rejects_reused_foreign_ahk(monkeypatch):
    """CORE-001: a PID reused by a foreign AutoHotkey process must NOT be
    terminated. Image-name equality is not ownership; the command-line check on
    the pinned handle must catch the foreign script. The stop still reports
    KILL_FAILED because we cannot prove our own instance exited."""
    killed, closed = [], []
    monkeypatch.setattr(ag.win32api, "OpenProcess",
                        lambda acc, inh, pid: pid)
    monkeypatch.setattr(ag.win32process, "GetModuleFileNameEx",
                        lambda h, i: r"C:\Other\AutoHotkeyU64.exe")
    monkeypatch.setattr(ag.win32process, "GetProcessId", lambda h: 101)
    # The (reused) pid's command line is NOT our script -> ownership fails.
    monkeypatch.setattr(ag, "_pid_cmdline",
                        lambda pid: "AutoHotkeyU64.exe C:\\foreign.ahk")
    monkeypatch.setattr(ag, "_cmdline_launches_our_script", lambda cmd: False)
    monkeypatch.setattr(ag.win32api, "TerminateProcess",
                        lambda h, c: killed.append(h))
    monkeypatch.setattr(ag.win32api, "CloseHandle", lambda h: closed.append(h))
    monkeypatch.setattr(ag.win32event, "WaitForSingleObject",
                        lambda h, ms: 0)
    res = ag._stop_pids([101])
    assert killed == []        # foreign AHK never terminated
    assert 101 in closed      # foreign handle closed
    assert res == "KILL_FAILED"


def test_stop_pids_open_failure_skips(monkeypatch):
    killed = []
    monkeypatch.setattr(ag.win32api, "OpenProcess",
                        lambda *a: (_ for _ in ()).throw(
                            __import__("pywintypes").error(5)))
    monkeypatch.setattr(ag.win32api, "TerminateProcess",
                        lambda h, c: killed.append(h))
    ag._stop_pids([101])
    assert killed == []


# --- T-184: verified data keeps its OWN clock ---------------------------------

def test_scan_failure_does_not_refresh_verified_age(monkeypatch):
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    monkeypatch.setattr(ag, "_last_verified_ts", 0.0)
    monkeypatch.setattr(ag, "_last_scan_pids", [111])
    monkeypatch.setattr(ag.time, "monotonic", lambda: 5.0)

    def boom(ps_cmd):
        raise OSError("scan unavailable")

    monkeypatch.setattr(ag, "_probe_entries", boom)
    state, pids = ag._find_our_pids(force=True)
    assert state == "failed"
    assert ag._last_verified_ts == 0.0  # NOT bumped to 5.0 by the failure
    assert ag._last_scan_pids == [111]  # ownership evidence retained


def test_repeated_failures_do_not_extend_verified_ttl(monkeypatch):
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    monkeypatch.setattr(ag, "_last_verified_ts", 0.0)
    monkeypatch.setattr(ag, "_last_scan_pids", [111])
    t = {"v": 0.0}

    def clock():
        t["v"] += 5.0
        return t["v"]

    monkeypatch.setattr(ag.time, "monotonic", clock)

    def boom(ps_cmd):
        raise OSError("scan unavailable")

    monkeypatch.setattr(ag, "_probe_entries", boom)
    for _ in range(5):
        ag._find_our_pids(force=True)
    assert ag._last_verified_ts == 0.0  # still the ORIGINAL verified time


def test_is_running_unknown_when_cache_expired_and_scan_fails(monkeypatch):
    """Expired verified cache + failed scan => UNKNOWN (None), never True."""
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 111)
    monkeypatch.setattr(ag, "_last_scan_ts", 0.0)
    monkeypatch.setattr(ag, "_last_verified_ts", 0.0)
    monkeypatch.setattr(ag, "_last_scan_pids", [111])
    monkeypatch.setattr(ag.time, "monotonic", lambda: 100.0)  # past 30s TTL
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("failed", []))
    assert ag.is_running() is None


def test_is_running_verified_fresh_stays_true(monkeypatch):
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 111)
    monkeypatch.setattr(ag, "_last_verified_ts", 10.0)
    monkeypatch.setattr(ag, "_last_scan_pids", [111])
    monkeypatch.setattr(ag.time, "monotonic", lambda: 20.0)  # inside 30s TTL
    monkeypatch.setattr(ag, "_pid_is_ahk_image", lambda pid: True)
    scanned = []
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: scanned.append(1) or ("cached", [111]))
    assert ag.is_running() is True
    assert scanned == []


# --- T-183: stop_ahk result contract ------------------------------------------

def test_stop_ahk_scan_failure_keeps_ownership(monkeypatch):
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 111)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("failed", []))
    removed = []
    monkeypatch.setattr(ag.os, "remove", lambda p: removed.append(p))
    monkeypatch.setattr(ag, "_stop_pids", lambda pids, wait_ms=500: None)
    monkeypatch.setattr(ag, "_last_scan_pids", [111])
    res = ag.stop_ahk()
    assert res == "UNKNOWN_IDENTITY"
    assert removed == []  # PID tracking evidence retained
    assert ag._last_scan_pids == [111]  # cache NOT erased as "stopped"


def test_stop_ahk_already_stopped_when_verified_empty(monkeypatch):
    monkeypatch.setattr(ag, "_read_pidfile", lambda: None)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("ok", []))
    removed = []
    monkeypatch.setattr(ag.os, "remove", lambda p: removed.append(p))
    res = ag.stop_ahk()
    assert res == "ALREADY_STOPPED"


def test_stop_ahk_stops_verified_pids(monkeypatch):
    killed = []
    monkeypatch.setattr(ag, "_read_pidfile", lambda: 111)
    monkeypatch.setattr(ag, "_find_our_pids",
                        lambda force=False: ("ok", [111]))
    monkeypatch.setattr(ag, "_stop_pids",
                        lambda pids, wait_ms=500: killed.extend(pids))
    monkeypatch.setattr(ag.os, "remove", lambda p: None)
    res = ag.stop_ahk()
    assert res == "STOPPED"
    assert killed == [111]
    assert ag._last_scan_pids == []
