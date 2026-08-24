"""W2-005 regression: AutoContinue must not clobber externally hot-reloaded buttons.

The AutoContinue engine may rewrite the buttons list out-of-process (game-driven
hot reload). The tab's save() used to unconditionally overwrite on-disk buttons
with its in-memory startup snapshot, so any later scalar/monitor/quit save
silently discarded the engine's newer buttons. Fix: only write buttons when the
GUI has a pending button edit (self._buttons_dirty); otherwise preserve whatever
is currently on disk.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import process_runner  # noqa: E402
from engine_config import canonical_default  # noqa: E402


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


def _btn(name):
    return {"name": name, "region": [0, 0, 1, 1],
            "template": "templates/buttons/%s.png" % name, "threshold": 0.8}


def _write_config(tmp_path, buttons):
    cfg = canonical_default("autocontinue_config.json")
    cfg["buttons"] = buttons
    path = tmp_path / "autocontinue_config.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def _read_buttons(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("buttons")


def test_buttons_dirty_false_after_init(tmp_path, monkeypatch):
    import tabs.auto_tab as at
    pytest.importorskip("tkinter")
    _write_config(tmp_path, [_btn("A")])
    monkeypatch.setattr(at, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = at.AutoContinueTab(root)
        assert tab._buttons_dirty is False
    finally:
        root.destroy()


def test_external_hot_reload_buttons_preserved_on_scalar_save(tmp_path, monkeypatch):
    import tabs.auto_tab as at
    pytest.importorskip("tkinter")
    # Initial state as the GUI saw it on load.
    _write_config(tmp_path, [_btn("A"), _btn("B")])
    monkeypatch.setattr(at, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = at.AutoContinueTab(root)
        # Simulate the engine hot-reloading buttons OUT-OF-PROCESS, changing the
        # on-disk list while the GUI still holds the stale startup snapshot.
        external = [_btn("C"), _btn("D"), _btn("E")]
        _write_config(tmp_path, external)
        # A scalar save with NO button edit in the GUI must NOT clobber them.
        assert tab.save(silent=True) is True
        assert _read_buttons(tab.cfg_path) == external
        # And the GUI's stale snapshot is still untouched.
        assert [b["name"] for b in tab.buttons] == ["A", "B"]
        # The scalar edit itself was still persisted.
        with open(tab.cfg_path, encoding="utf-8") as f:
            saved = json.load(f)
        assert float(tab.poll_interval.get()) == saved["poll_interval_sec"]
    finally:
        root.destroy()


def test_pending_button_edit_is_written(tmp_path, monkeypatch):
    import tabs.auto_tab as at
    pytest.importorskip("tkinter")
    _write_config(tmp_path, [_btn("A"), _btn("B")])
    monkeypatch.setattr(at, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = at.AutoContinueTab(root)
        # User removes a button -> pending button edit.
        tab.tree.selection_set("0")
        tab.remove_button()
        assert tab._buttons_dirty is True
        assert [b["name"] for b in tab.buttons] == ["B"]
        # Save must persist the user's edit, not the (now stale) disk buttons.
        assert tab.save(silent=True) is True
        assert _read_buttons(tab.cfg_path) == [_btn("B")]
        # After a successful save the pending edit is cleared.
        assert tab._buttons_dirty is False
    finally:
        root.destroy()


def test_reset_defaults_persists_canonical_buttons(tmp_path, monkeypatch):
    import tabs.auto_tab as at
    pytest.importorskip("tkinter")
    _write_config(tmp_path, [_btn("A")])
    monkeypatch.setattr(at, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    root = _new_root()
    try:
        tab = at.AutoContinueTab(root)
        tab.reset_defaults()
        # reset_defaults sets a pending button edit (dirty) and schedules an
        # auto-save via after(); in a headless test we flush it directly.
        assert tab._buttons_dirty is True
        assert tab.save(silent=True) is True
        # canonical buttons must be written and disk must NOT keep the "A" button.
        canonical = canonical_default("autocontinue_config.json")["buttons"]
        assert _read_buttons(tab.cfg_path) == canonical
    finally:
        root.destroy()
