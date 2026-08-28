"""W2-003 / W2-004 regression: explicit PvP sidecar state + fail-safe publication.

W2-003: a missing runtime-trigger file used to mean BOTH "first run (never
applied)" and "explicitly stopped". Stop now persists an explicit INACTIVE
marker so DeathWatch's _pvp_trigger_vk returns None instead of falling back to
config.json and re-arming PvP after the user stopped.

W2-004: _write_runtime_trigger swallowed every exception and left any stale
active file authoritative. It now returns strict True/False and tears the
sidecar down on failure so a failed publish can never leave a stale trigger.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import deathwatch  # noqa: E402


def _sidecar_paths(monkeypatch, tmp_path):
    """Point the two sidecar constants at tmp files so tests never touch the real
    project directory."""
    active = str(tmp_path / ".runtime_pvp_trigger")
    inactive = str(tmp_path / ".runtime_pvp_trigger_inactive")
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_PATH", active)
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_INACTIVE_PATH", inactive)
    return active, inactive


def _stub_combos(monkeypatch, combos):
    monkeypatch.setattr(deathwatch.ahk_builder, "_active_combos",
                        lambda d: (combos, []))


# --- W2-004: strict, fail-safe publication --------------------------------

def test_remove_if_present_distinguishes_absent_from_failure(monkeypatch, tmp_path):
    """CORE-005: _remove_if_present returns False on absent (no exception)
    and raises OSError on real deletion failure (so callers can fail
    closed instead of silently treating failure as absence)."""
    present = str(tmp_path / "present.txt")
    absent = str(tmp_path / "absent.txt")
    with open(present, "w") as f:
        f.write("")
    assert deathwatch._remove_if_present(present) is True
    assert deathwatch._remove_if_present(absent) is False
    # Locked-file simulation: readonly on Windows fails Delete; Linux same.
    locked = str(tmp_path / "locked.txt")
    with open(locked, "w") as f:
        f.write("x")
    import stat
    os.chmod(locked, stat.S_IRUSR)  # read-only
    try:
        if os.name != "nt":
            with pytest.raises(OSError):
                deathwatch._remove_if_present(locked)
    finally:
        os.chmod(locked, stat.S_IRUSR | stat.S_IWUSR)
        os.remove(locked)


def test_active_publish_inactive_remove_failure_reports_false(monkeypatch, tmp_path):
    """CORE-005: active VK writes successfully but a stale inactive file
    cannot be deleted -> report False, do not pretend success. The reader
    still resolves to None because the inactive marker is still there."""
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    _stub_combos(monkeypatch, [{"tag": "ryze_pvp", "triggers": ["F15"]}])
    with open(inactive, "w") as f:
        f.write("")
    # Force inactive remove to fail: replace the path with an unreadable dir
    # so os.remove raises IsADirectoryError or PermissionError.
    import stat
    blocker = str(tmp_path / "blocker_dir")
    os.mkdir(blocker)
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_INACTIVE_PATH", blocker)
    assert deathwatch._write_runtime_trigger({"mode": "ryze"}) is False
    # Active file was written but caller is told truth.
    assert os.path.exists(active)


def test_inactive_publish_active_remove_failure_still_authoritative(monkeypatch, tmp_path):
    """CORE-005: inactive is published FIRST. A subsequent failure to
    remove the stale active file is non-fatal: the inactive marker is
    authoritative so the reader still returns None."""
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    _stub_combos(monkeypatch, [])
    # Pre-existing active file that we cannot remove.
    with open(active, "w") as f:
        f.write("999")
    blocker = str(tmp_path / "active_dir")
    os.mkdir(blocker)
    monkeypatch.setattr(deathwatch, "_RUNTIME_TRIGGER_PATH", blocker)
    assert deathwatch._set_runtime_inactive() is True
    # Inactive marker was published and is authoritative.
    assert os.path.exists(inactive)
    assert deathwatch._pvp_trigger_vk() is None


def test_interruption_never_permits_stale_active_fallback(monkeypatch, tmp_path):
    """CORE-005: a crash-equivalent interruption between active write and
    inactive remove must leave the reader fail-safe. We simulate by
    publishing the active file directly, then asserting _pvp_trigger_vk
    only honors it when no inactive marker exists."""
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    # State A: only active present -> reader honors it.
    with open(active, "w") as f:
        f.write(str(0x7E))
    assert deathwatch._pvp_trigger_vk() == 0x7E
    # State B: active + inactive -> reader returns None (inactive wins).
    with open(inactive, "w") as f:
        f.write("")
    assert deathwatch._pvp_trigger_vk() is None
    # State C: inactive alone -> reader returns None.
    os.remove(active)
    assert deathwatch._pvp_trigger_vk() is None


def test_successful_active_transition_only_active_visible(monkeypatch, tmp_path):
    """CORE-005: a successful active publication leaves only the active
    sidecar; the inactive marker is gone and the reader returns the VK."""
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    _stub_combos(monkeypatch, [{"tag": "ryze_pvp", "triggers": ["F15"]}])
    with open(inactive, "w") as f:
        f.write("")
    assert deathwatch._write_runtime_trigger({"mode": "ryze"}) is True
    assert os.path.exists(active)
    assert not os.path.exists(inactive)
    assert deathwatch._pvp_trigger_vk() == 0x7E


def test_successful_inactive_transition_authoritative(monkeypatch, tmp_path):
    """CORE-005: a successful inactive publication leaves only the
    inactive marker; the reader returns None even if a stale active file
    happens to exist elsewhere."""
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    with open(active, "w") as f:
        f.write(str(0x7E))
    _stub_combos(monkeypatch, [])
    assert deathwatch._set_runtime_inactive() is True
    assert os.path.exists(inactive)
    assert deathwatch._pvp_trigger_vk() is None


def test_write_active_writes_vk_and_clears_inactive(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    _stub_combos(monkeypatch, [{"tag": "ryze_pvp", "triggers": ["F15"]}])
    # Pre-existing stale inactive marker must be removed on a successful active write.
    with open(inactive, "w") as f:
        f.write("")
    assert deathwatch._write_runtime_trigger({"mode": "ryze"}) is True
    assert os.path.exists(active)
    assert not os.path.exists(inactive)
    with open(active) as f:
        assert f.read().strip() == str(0x7E)


def test_write_no_pvp_writes_inactive(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    _stub_combos(monkeypatch, [{"tag": "ryze_wave", "triggers": ["F13"]}])
    # Pre-existing active file must be removed when there is no PvP combo.
    with open(active, "w") as f:
        f.write("999")
    assert deathwatch._write_runtime_trigger({"mode": "ryze"}) is True
    assert os.path.exists(inactive)
    assert not os.path.exists(active)


def test_write_unsendable_vk_writes_inactive(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    # A PvP combo whose trigger cannot be turned into a sendable VK (keybd_event
    # restart cannot fire it) -> explicit inactive state.
    _stub_combos(monkeypatch, [{"tag": "ryze_pvp", "triggers": ["BogusKeyToken"]}])
    assert deathwatch._write_runtime_trigger({"mode": "ryze"}) is True
    assert os.path.exists(inactive)
    assert not os.path.exists(active)


def test_write_failure_returns_false_and_tears_down(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    _stub_combos(monkeypatch, [{"tag": "ryze_pvp", "triggers": ["F15"]}])
    # Make the atomic replace fail so the write cannot complete.
    monkeypatch.setattr(deathwatch.os, "replace",
                        lambda src, dst: (_ for _ in ()).throw(OSError("boom")))
    # A stale active file must NOT survive a failed publish.
    with open(active, "w") as f:
        f.write("999")
    assert deathwatch._write_runtime_trigger({"mode": "ryze"}) is False
    assert not os.path.exists(active)
    assert not os.path.exists(inactive)


def test_write_cannot_derive_state_fails_safe(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    monkeypatch.setattr(deathwatch.ahk_builder, "_active_combos",
                        lambda d: (_ for _ in ()).throw(ValueError("bad")))
    with open(active, "w") as f:
        f.write("999")
    assert deathwatch._write_runtime_trigger({"mode": "ryze"}) is False
    assert not os.path.exists(active)


# --- W2-003: explicit inactive state ---------------------------------------

def test_set_runtime_inactive_writes_marker(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    with open(active, "w") as f:
        f.write("999")
    assert deathwatch._set_runtime_inactive() is True
    assert os.path.exists(inactive)
    assert not os.path.exists(active)


def test_clear_runtime_trigger_removes_both(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    with open(active, "w") as f:
        f.write("1")
    with open(inactive, "w") as f:
        f.write("")
    deathwatch._clear_runtime_trigger()
    assert not os.path.exists(active)
    assert not os.path.exists(inactive)


def test_pvp_trigger_vk_reads_active_file(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    with open(active, "w") as f:
        f.write(str(0x7E))
    # No inactive marker -> active file is authoritative.
    assert deathwatch._pvp_trigger_vk() == 0x7E


def test_pvp_trigger_vk_inactive_marker_wins_over_config(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    with open(inactive, "w") as f:
        f.write("")
    # Even if config.json would yield a PvP combo, the explicit inactive marker
    # must take precedence and return None (W2-003 core).
    monkeypatch.setattr(deathwatch.config_store, "validate_config",
                        lambda d: False)
    monkeypatch.setattr(deathwatch.ahk_builder, "_active_combos",
                        lambda d: ([{"tag": "ryze_pvp", "triggers": ["F15"]}], []))
    assert deathwatch._pvp_trigger_vk() is None


def test_pvp_trigger_vk_no_sidecar_falls_back_to_config(monkeypatch, tmp_path):
    active, inactive = _sidecar_paths(monkeypatch, tmp_path)
    # No sidecar files -> first-run semantics: derive from config.json path.
    monkeypatch.setattr(deathwatch.config_store, "validate_config",
                        lambda d: False)
    monkeypatch.setattr(deathwatch.ahk_builder, "_active_combos",
                        lambda d: ([{"tag": "ryze_pvp", "triggers": ["F15"]}], []))
    assert deathwatch._pvp_trigger_vk() == 0x7E
