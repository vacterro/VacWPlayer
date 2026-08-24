"""CORE-012 regression: engine tabs must NOT auto-start their subprocess
against a missing (materialization failed) or invalid/unvalidated config.

Both ``deathwatch_config.json`` and ``surrender_config.json`` ship with
``monitor_enabled: True`` as their canonical default (engine_config.py lines
109 / 142). The old code derived ``mon_enabled`` directly from that canonical
default on a missing-file path, so a *failed* materialization (disk/permission,
or ``update_json`` returning False) left ``mon_enabled = True`` and the tab
launched the child against a file that ``load_config()`` would FATAL on.

The fix routes every start through ``resolve_monitor_state(load_status, ...)``
+ a ``_config_usable`` flag, so only a config that is present AND validated
("ok") is ever authorized to start the child.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tabs.tab_config import resolve_monitor_state

import process_runner
import tabs.tab_config as tc

# Death/surrender tabs import tkinter at module load, so they are imported
# lazily inside the integration tests (after importorskip guards them).


# --------------------------------------------------------------------------
# Pure gate logic - deterministic, no GUI.
# --------------------------------------------------------------------------

def test_resolve_monitor_state_ok_true():
    on, usable = resolve_monitor_state("ok", {"monitor_enabled": True})
    assert on is True and usable is True


def test_resolve_monitor_state_ok_false():
    on, usable = resolve_monitor_state("ok", {"monitor_enabled": False})
    assert on is False and usable is True


def test_resolve_monitor_state_ok_missing_key_uses_default():
    on, usable = resolve_monitor_state("ok", {}, default_monitor_enabled=True)
    assert on is True and usable is True
    on, usable = resolve_monitor_state("ok", {}, default_monitor_enabled=False)
    assert on is False and usable is True


def test_resolve_monitor_state_missing_not_usable():
    # CORE-012 core: canonical default ships monitor_enabled=True, but a
    # missing file (materialization failed) must NOT authorize a start.
    on, usable = resolve_monitor_state(
        "missing", {}, default_monitor_enabled=True)
    assert on is False and usable is False


def test_resolve_monitor_state_invalid_statuses_not_usable():
    for status in ("corrupt", "io_error", "semantic_invalid", "wrong_shape"):
        on, usable = resolve_monitor_state(
            status, {}, default_monitor_enabled=True)
        assert (on, usable) == (False, False), status


# --------------------------------------------------------------------------
# Integration: the tab wiring honors the gate (real Tk root, isolated cfg dir).
# --------------------------------------------------------------------------

def _new_root():
    pytest.importorskip("tkinter")
    import tkinter as tk
    r = tk.Tk()
    r.withdraw()
    return r


def _capture_spawns(monkeypatch):
    calls = []
    monkeypatch.setattr(process_runner.ProcessRunner, "start",
                        lambda self, a: (calls.append(a) or True))
    monkeypatch.setattr(process_runner.ProcessRunner, "stop",
                        lambda self: True)
    return calls


def test_death_tab_success_materialization_starts(tmp_path, monkeypatch):
    import tabs.death_tab as dt
    pytest.importorskip("tkinter")
    monkeypatch.setattr(dt, "BASE", str(tmp_path))
    calls = _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = dt.DeathWatchTab(root)
        # First run: canonical default (monitor_enabled=True) materialized OK,
        # so the child IS authorized to start.
        assert tab._config_usable is True
        assert tab.monitor_var.get() is True
        assert calls == [["--replace"]]
        assert os.path.exists(tab.cfg_path)
    finally:
        root.destroy()


def test_death_tab_failed_materialization_no_start(tmp_path, monkeypatch):
    import tabs.death_tab as dt
    pytest.importorskip("tkinter")
    # Force the missing-file materialization to FAIL (save_json returns False).
    monkeypatch.setattr(tc, "save_json", lambda *a, **k: False)
    monkeypatch.setattr(dt, "BASE", str(tmp_path))
    calls = _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = dt.DeathWatchTab(root)
        # CORE-012: even though the canonical default ships monitor_enabled=True,
        # a failed materialization must NOT launch the child.
        assert tab._config_usable is False
        assert tab.monitor_var.get() is False
        assert calls == []
        assert not os.path.exists(tab.cfg_path)
    finally:
        root.destroy()


def test_surrender_tab_success_materialization_starts(tmp_path, monkeypatch):
    import tabs.surrender_tab as st
    pytest.importorskip("tkinter")
    monkeypatch.setattr(st, "BASE", str(tmp_path))
    calls = _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = st.SurrenderTab(root)
        assert tab._config_usable is True
        assert tab.monitor_var.get() is True
        assert calls == [["--replace"]]
        assert os.path.exists(tab.cfg_path)
    finally:
        root.destroy()


def test_surrender_tab_failed_materialization_no_start(tmp_path, monkeypatch):
    import tabs.surrender_tab as st
    pytest.importorskip("tkinter")
    # Force the missing-file materialization to FAIL (update_json returns False).
    monkeypatch.setattr(st, "update_json", lambda *a, **k: False)
    monkeypatch.setattr(st, "BASE", str(tmp_path))
    calls = _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = st.SurrenderTab(root)
        assert tab._config_usable is False
        assert tab.monitor_var.get() is False
        assert calls == []
        assert not os.path.exists(tab.cfg_path)
    finally:
        root.destroy()


def test_death_tab_present_corrupt_no_start(tmp_path, monkeypatch):
    import tabs.death_tab as dt
    pytest.importorskip("tkinter")
    # A present-but-corrupt config must force monitor OFF (no child start).
    with open(os.path.join(tmp_path, "deathwatch_config.json"), "w") as f:
        f.write("{ this is not valid json")
    monkeypatch.setattr(dt, "BASE", str(tmp_path))
    calls = _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = dt.DeathWatchTab(root)
        assert tab._config_usable is False
        assert tab.monitor_var.get() is False
        assert calls == []
    finally:
        root.destroy()


def test_safe_start_gate_blocks_when_not_usable(tmp_path, monkeypatch):
    import tabs.death_tab as dt
    pytest.importorskip("tkinter")
    monkeypatch.setattr(dt, "BASE", str(tmp_path))
    calls = _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = dt.DeathWatchTab(root)  # success path -> started once
        calls.clear()
        # Simulate a degraded state: config no longer usable.
        tab._config_usable = False
        result = tab._safe_start()
        assert result is False
        assert calls == []  # child was NOT spawned
        assert tab.monitor_var.get() is False
    finally:
        root.destroy()


def test_toggle_monitor_on_after_save_starts(tmp_path, monkeypatch):
    import tabs.death_tab as dt
    pytest.importorskip("tkinter")
    monkeypatch.setattr(dt, "BASE", str(tmp_path))
    calls = _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = dt.DeathWatchTab(root)  # success -> already started once
        calls.clear()
        # User turns the monitor OFF, then back ON.
        tab.monitor_var.set(False)
        tab.toggle_monitor()           # stop path, no start
        assert calls == []
        tab.monitor_var.set(True)
        tab.toggle_monitor()           # save() succeeds -> _safe_start launches
        assert calls == [["--replace"]]
    finally:
        root.destroy()
