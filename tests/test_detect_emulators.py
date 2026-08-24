"""PERF-003 regression: emulator detection must perform ONE bounded tasklist
enumeration instead of N blocking per-exe subprocesses, and must never raise /
freeze the caller. Pure mock of subprocess.check_output."""

from tabs.main_tab import detect_running_emulators, _enumerate_running_exes


def test_enumerate_parses_csv(monkeypatch):
    csv = (
        '"HD-Player.exe","1234","Console","1","12345 K"\n'
        '"notepad.exe","99","Console","1","1024 K"\n'
    )
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: csv)
    names = _enumerate_running_exes()
    assert names is not None
    assert "hd-player.exe" in names
    assert "notepad.exe" in names


def test_detect_returns_only_emulators(monkeypatch):
    csv = (
        '"HD-Player.exe","1234","Console","1","1 K"\n'
        '"BlueStacks.exe","2","Console","1","1 K"\n'
        '"notepad.exe","3","Console","1","1 K"\n'
    )
    monkeypatch.setattr("subprocess.check_output", lambda *a, **k: csv)
    found = detect_running_emulators()
    assert set(found) == {"HD-Player.exe", "BlueStacks.exe"}


def test_detect_returns_empty_on_failure(monkeypatch):
    import subprocess

    def boom(*a, **k):
        raise subprocess.CalledProcessError(1, "tasklist")

    monkeypatch.setattr("subprocess.check_output", boom)
    # Failure must yield [] (UNKNOWN), never raise out of the call.
    assert detect_running_emulators() == []
