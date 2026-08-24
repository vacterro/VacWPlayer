"""W2-001 regression: strict Boolean quit persistence.

Before this fix, ``quit_app`` treated *everything except literal ``False``* as a
successful save (``all(v is not False ...)``). A tab ``save()`` that hit an
invalid-numeric ``ValueError`` did a bare ``return`` -> ``None``, which the
old gate misread as "saved fine". So an edit that failed validation could let
the app tear down and silently discard *other* (actually valid) edits, with no
named culprit.

The fix has two halves:
  * every tab ``save()`` now returns ``False`` (not ``None``) on validation
    failure, and ``True`` only on an actual successful disk write;
  * ``quit_app`` routes every result through ``_evaluate_quit_persistence``,
    which requires literal ``True`` and names every non-True component so a
    normal quit fails CLOSED (stays alive) and force-quit still tears down.

These tests exercise both halves: the pure contract, the real tab save()s, and
the full ``quit_app`` branching with a lightweight harness.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main as main_mod  # noqa: E402
import process_runner  # noqa: E402


# --------------------------------------------------------------------------
# Pure contract: _evaluate_quit_persistence (no GUI, deterministic).
# --------------------------------------------------------------------------

def test_eval_all_true_ok():
    ok, failed = main_mod._evaluate_quit_persistence(
        {"DeathWatchTab": True, "BuyTab": True}, True)
    assert ok is True
    assert failed == []


def test_eval_one_false_named():
    ok, failed = main_mod._evaluate_quit_persistence(
        {"DeathWatchTab": False, "BuyTab": True}, True)
    assert ok is False
    assert failed == ["DeathWatchTab"]


def test_eval_accidental_none_fails_closed():
    # A stray None (any non-True) must count as failure, not "looks truthy".
    ok, failed = main_mod._evaluate_quit_persistence(
        {"DeathWatchTab": None, "BuyTab": True}, True)
    assert ok is False
    assert "DeathWatchTab" in failed


def test_eval_main_config_failure_named():
    ok, failed = main_mod._evaluate_quit_persistence(
        {"BuyTab": True}, False)
    assert ok is False
    assert "main config" in failed


def test_eval_empty_tabs_ok_when_saved_true():
    ok, failed = main_mod._evaluate_quit_persistence({}, True)
    assert ok is True
    assert failed == []


def test_eval_multiple_failures_named():
    ok, failed = main_mod._evaluate_quit_persistence(
        {"DeathWatchTab": False, "BuyTab": None, "AcceptTab": True}, False)
    assert ok is False
    assert set(failed) == {"DeathWatchTab", "BuyTab", "main config"}


# --------------------------------------------------------------------------
# Real tab save() must return False (not None) on invalid numeric input.
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


def _assert_no_bad_value_on_disk(tab, bad):
    """An invalid save must NOT persist the bad text to disk."""
    if os.path.exists(tab.cfg_path):
        with open(tab.cfg_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert bad not in content, "invalid numeric was persisted to disk"


def test_death_tab_invalid_numeric_returns_false(tmp_path, monkeypatch):
    import tabs.death_tab as dt
    pytest.importorskip("tkinter")
    monkeypatch.setattr(dt, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = dt.DeathWatchTab(root)
        bad = "not-a-float"
        tab.poll_interval.set(bad)
        result = tab.save(silent=True)
        assert result is False
        _assert_no_bad_value_on_disk(tab, bad)
    finally:
        root.destroy()


def test_accept_tab_invalid_numeric_returns_false(tmp_path, monkeypatch):
    import tabs.accept_tab as at
    pytest.importorskip("tkinter")
    monkeypatch.setattr(at, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = at.AcceptTab(root)
        bad = "xx"
        tab.poll_interval.set(bad)
        result = tab.save(silent=True)
        assert result is False
        _assert_no_bad_value_on_disk(tab, bad)
    finally:
        root.destroy()


def test_buy_tab_invalid_numeric_returns_false(tmp_path, monkeypatch):
    import tabs.buy_tab as bt
    pytest.importorskip("tkinter")
    monkeypatch.setattr(bt, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = bt.BuyTab(root)
        bad = "zzz"
        tab.quickbuy_presses.set(bad)  # int("zzz") -> ValueError
        result = tab.save(silent=True)
        assert result is False
        _assert_no_bad_value_on_disk(tab, bad)
    finally:
        root.destroy()


def test_auto_tab_invalid_numeric_returns_false(tmp_path, monkeypatch):
    import tabs.auto_tab as aut
    pytest.importorskip("tkinter")
    monkeypatch.setattr(aut, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = aut.AutoContinueTab(root)
        bad = "??"
        tab.poll_interval.set(bad)
        result = tab.save(silent=True)
        assert result is False
        _assert_no_bad_value_on_disk(tab, bad)
    finally:
        root.destroy()


def test_surrender_tab_invalid_numeric_returns_false(tmp_path, monkeypatch):
    import tabs.surrender_tab as st
    pytest.importorskip("tkinter")
    monkeypatch.setattr(st, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = st.SurrenderTab(root)
        bad = "no"
        tab.poll_interval.set(bad)
        result = tab.save(silent=True)
        assert result is False
        _assert_no_bad_value_on_disk(tab, bad)
    finally:
        root.destroy()


def test_buy_tab_valid_save_returns_true(tmp_path, monkeypatch):
    import tabs.buy_tab as bt
    pytest.importorskip("tkinter")
    monkeypatch.setattr(bt, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = bt.BuyTab(root)
        tab.quickbuy_presses.set("3")
        tab.quickbuy_window_ms.set("150.0")
        tab.buy_delay_sec.set("0.5")
        tab.buy_then_mid_delay.set("1.0")
        result = tab.save(silent=True)
        assert result is True
        assert os.path.exists(tab.cfg_path)
    finally:
        root.destroy()


# --------------------------------------------------------------------------
# Full quit_app branching via a lightweight harness (real method, fake tabs).
# --------------------------------------------------------------------------

def _make_fake_tab(cls_name, result):
    klass = type(cls_name, (), {})

    def save(silent=False):
        return result

    inst = klass()
    inst.save = save
    return inst


def _make_quit_harness(monkeypatch, tab_results, saved):
    w = object.__new__(main_mod.VacWPlayer)
    w.config = {"mode": "general"}
    w.tab_death = _make_fake_tab("DeathWatchTab",
                                 tab_results.get("DeathWatchTab", True))
    w.tab_buy = _make_fake_tab("BuyTab", tab_results.get("BuyTab", True))
    w.tab_auto = _make_fake_tab("AutoContinueTab",
                                tab_results.get("AutoContinueTab", True))
    w.tab_accept = _make_fake_tab("AcceptTab",
                                  tab_results.get("AcceptTab", True))
    w.tab_surrender = _make_fake_tab("SurrenderTab",
                                     tab_results.get("SurrenderTab", True))
    w.tray_icon = None
    w.collect_config = lambda: None
    state = {"stop": False, "destroy": False}

    class FakeRoot:
        def after(self, ms, cb):
            # Simulate the Tk mainloop eventually servicing the scheduled call.
            state["after"] = (ms, cb)
            cb()
            return 1

        def destroy(self):
            state["destroy"] = True

    w.root = FakeRoot()
    w.stop_everything = lambda: state.__setitem__("stop", True)
    monkeypatch.setattr(main_mod, "save_config",
                        lambda config, bypass_guard=False: saved)
    return w, state


def test_quit_all_ok_tears_down(tmp_path, monkeypatch, capsys):
    w, state = _make_quit_harness(
        monkeypatch,
        {"DeathWatchTab": True, "BuyTab": True, "AutoContinueTab": True,
         "AcceptTab": True, "SurrenderTab": True}, True)
    w.quit_app()
    assert state["stop"] is True
    assert state["destroy"] is True
    assert "aborted" not in capsys.readouterr().err


def test_quit_one_tab_fails_normal_aborts(tmp_path, monkeypatch, capsys):
    w, state = _make_quit_harness(
        monkeypatch,
        {"DeathWatchTab": False, "BuyTab": True, "AutoContinueTab": True,
         "AcceptTab": True, "SurrenderTab": True}, True)
    w.quit_app()  # normal
    # Fail-closed: no teardown, app stays alive.
    assert state["stop"] is False
    assert state["destroy"] is False
    err = capsys.readouterr().err
    assert "aborted" in err
    assert "DeathWatchTab" in err


def test_quit_one_tab_fails_force_tears_down(tmp_path, monkeypatch, capsys):
    w, state = _make_quit_harness(
        monkeypatch,
        {"DeathWatchTab": True, "BuyTab": False, "AutoContinueTab": True,
         "AcceptTab": True, "SurrenderTab": True}, True)
    w.quit_app(force=True)
    # Force-quit still performs required safety teardown ...
    assert state["stop"] is True
    assert state["destroy"] is True
    # ... but the same failure is logged and named.
    err = capsys.readouterr().err
    assert "force quit" in err
    assert "BuyTab" in err


def test_quit_main_config_fails_normal_aborts(tmp_path, monkeypatch, capsys):
    w, state = _make_quit_harness(
        monkeypatch,
        {"DeathWatchTab": True, "BuyTab": True, "AutoContinueTab": True,
         "AcceptTab": True, "SurrenderTab": True}, False)
    w.quit_app()  # normal, but main config save failed
    assert state["stop"] is False
    assert state["destroy"] is False
    err = capsys.readouterr().err
    assert "main config" in err


def test_quit_main_config_fails_force_tears_down(tmp_path, monkeypatch, capsys):
    w, state = _make_quit_harness(
        monkeypatch,
        {"DeathWatchTab": True, "BuyTab": True, "AutoContinueTab": True,
         "AcceptTab": True, "SurrenderTab": True}, False)
    w.quit_app(force=True)
    assert state["stop"] is True
    assert state["destroy"] is True
    err = capsys.readouterr().err
    assert "main config" in err
