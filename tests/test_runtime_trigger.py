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
