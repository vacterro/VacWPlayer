"""W2-006 regression: template deletion must be bound to a VALUE identity,
never a positional index.

Both AcceptTab and SurrenderTab render the templates list into a Treeview whose
row ``iid`` used to be the item's positional index, and remove_template() then
deleted ``c["templates"][idx]`` inside the update_json() read-modify-write
lambda. That is a textbook TOCTOU: between the tree render (which told the user
"row 2 is C") and the RMW write, an external process (the engine's own hot
reload, a second GUI instance, a hand edit) can insert/remove/reorder items, so
the positional index now points at a DIFFERENT template -> the wrong one is
deleted.

Fix: capture the full template dict snapshot when rendering each row, and delete
by value-equality inside the RMW lambda. An external shift therefore cannot move
the target out from under the click.

These tests instantiate the REAL tabs under tkinter (BASE patched to tmp_path),
simulate the external change on disk AFTER the tree is built, then click the
already-rendered row and assert the identity-correct item is removed.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tabs.tab_config import remove_template_by_identity  # noqa: E402
from engine_config import canonical_default  # noqa: E402


# --------------------------------------------------------------------------
# Pure helper: remove_template_by_identity
# --------------------------------------------------------------------------

def _tpl(name, action=None, threshold=0.8):
    d = {"name": name, "file": "templates/%s.png" % name, "threshold": threshold}
    if action is not None:
        d["action"] = action
    return d


def test_exact_match_removes_correct_item_regardless_of_position():
    live = [_tpl("a"), _tpl("b"), _tpl("c")]
    identity = dict(live[1])  # user clicked "b"
    removed = remove_template_by_identity(live, identity)
    assert removed is True
    assert [t["name"] for t in live] == ["a", "c"]


def test_external_prepend_must_not_delete_wrong_item():
    # User rendered [a, b, c] and clicked the LAST row (c).
    identity = _tpl("c")
    # External process prepends an item BEFORE the RMW read.
    live = [_tpl("x"), _tpl("a"), _tpl("b"), _tpl("c")]
    removed = remove_template_by_identity(live, identity)
    assert removed is True
    # Positional code would have used idx=2 and deleted "b" (wrong). Value
    # identity deletes "c" (correct).
    assert [t["name"] for t in live] == ["x", "a", "b"]


def test_external_mid_insertion_must_not_delete_wrong_item():
    identity = _tpl("b")
    live = [_tpl("a"), _tpl("z"), _tpl("b"), _tpl("c")]  # z inserted before b
    removed = remove_template_by_identity(live, identity)
    assert removed is True
    assert [t["name"] for t in live] == ["a", "z", "c"]


def test_fallback_by_name_file_when_threshold_edited_externally():
    # Snapshot from render time had threshold 0.8; the live item was edited to
    # 0.9 externally. Exact match fails, so we fall back to (name, file).
    identity = _tpl("a", threshold=0.8)
    live = [_tpl("a", threshold=0.9)]
    removed = remove_template_by_identity(live, identity)
    assert removed is True
    assert live == []


def test_duplicate_identical_templates_removes_first():
    live = [_tpl("a"), _tpl("a")]
    removed = remove_template_by_identity(live, _tpl("a"))
    assert removed is True
    assert len(live) == 1


def test_no_match_leaves_list_unchanged_and_reports_false():
    live = [_tpl("a")]
    removed = remove_template_by_identity(live, _tpl("z"))
    assert removed is False
    assert [t["name"] for t in live] == ["a"]


def test_guards_reject_bad_inputs():
    assert remove_template_by_identity(None, _tpl("a")) is False
    assert remove_template_by_identity([], None) is False
    assert remove_template_by_identity("nope", _tpl("a")) is False


# --------------------------------------------------------------------------
# Integration: real tabs under tkinter, external change after render
# --------------------------------------------------------------------------

def _new_root():
    pytest.importorskip("tkinter")
    import tkinter as tk
    r = tk.Tk()
    r.withdraw()
    return r


def _capture_spawns(monkeypatch):
    import process_runner
    monkeypatch.setattr(process_runner.ProcessRunner, "start", lambda self, a: True)
    monkeypatch.setattr(process_runner.ProcessRunner, "stop", lambda self: True)


def _write_config(tmp_path, config_name, templates):
    cfg = canonical_default(config_name)
    cfg["templates"] = templates
    path = tmp_path / config_name
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return str(path)


def _read_names(path):
    with open(path, encoding="utf-8") as f:
        return [t["name"] for t in json.load(f)["templates"]]


def _spy_info(monkeypatch, mod):
    calls = []
    monkeypatch.setattr(mod.messagebox, "showinfo",
                        lambda *a, **k: calls.append(a))
    return calls


def test_accept_remove_by_identity_survives_external_prepend(tmp_path, monkeypatch):
    import tabs.accept_tab as at
    pytest.importorskip("tkinter")
    _write_config(tmp_path, "accept_config.json",
                  [_tpl("a"), _tpl("b"), _tpl("c")])
    monkeypatch.setattr(at, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    info_calls = _spy_info(monkeypatch, at)
    root = _new_root()
    try:
        tab = at.AcceptTab(root)
        # External process prepends "x" to the on-disk list AFTER the tree was
        # rendered (user already selected the last row, "c").
        _write_config(tmp_path, "accept_config.json",
                      [_tpl("x"), _tpl("a"), _tpl("b"), _tpl("c")])
        tab.tree.selection_set("2")  # the row the user clicked (c)
        tab.remove_template()
        # Identity-safe: c is removed, not b (which positional idx=2 would hit).
        assert _read_names(tab.cfg_path) == ["x", "a", "b"]
        assert info_calls == []  # success path shows no dialog
    finally:
        root.destroy()


def test_accept_remove_missing_identity_shows_dialog_no_delete(tmp_path, monkeypatch):
    import tabs.accept_tab as at
    pytest.importorskip("tkinter")
    _write_config(tmp_path, "accept_config.json",
                  [_tpl("a"), _tpl("b"), _tpl("c")])
    monkeypatch.setattr(at, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    info_calls = _spy_info(monkeypatch, at)
    root = _new_root()
    try:
        tab = at.AcceptTab(root)
        # External process DELETED c before the user clicked its row.
        _write_config(tmp_path, "accept_config.json", [_tpl("a"), _tpl("b")])
        tab.tree.selection_set("2")
        tab.remove_template()
        assert _read_names(tab.cfg_path) == ["a", "b"]  # nothing removed
        assert info_calls != []  # "no longer present" dialog shown
    finally:
        root.destroy()


def test_accept_no_selection_shows_dialog_no_write(tmp_path, monkeypatch):
    import tabs.accept_tab as at
    pytest.importorskip("tkinter")
    _write_config(tmp_path, "accept_config.json", [_tpl("a")])
    monkeypatch.setattr(at, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    info_calls = _spy_info(monkeypatch, at)
    update_calls = []
    monkeypatch.setattr(at, "update_json",
                        lambda *a, **k: (update_calls.append(a) or True))
    root = _new_root()
    try:
        tab = at.AcceptTab(root)
        tab.remove_template()
        assert info_calls != []
        assert update_calls == []  # no RMW attempted without a selection
    finally:
        root.destroy()


def test_surrender_remove_by_identity_survives_external_prepend(tmp_path, monkeypatch):
    import tabs.surrender_tab as st
    pytest.importorskip("tkinter")
    _write_config(tmp_path, "surrender_config.json",
                  [_tpl("a", "accept"), _tpl("b", "accept"), _tpl("c", "decline")])
    monkeypatch.setattr(st, "BASE", str(tmp_path))
    _capture_spawns(monkeypatch)
    info_calls = _spy_info(monkeypatch, st)
    root = _new_root()
    try:
        tab = st.SurrenderTab(root)
        _write_config(tmp_path, "surrender_config.json",
                      [_tpl("x", "accept"), _tpl("a", "accept"),
                       _tpl("b", "accept"), _tpl("c", "decline")])
        tab.tree.selection_set("2")  # the row the user clicked (c)
        tab.remove_template()
        # Action field is part of the snapshot, so "c" (decline) is matched
        # exactly even though a/b also carry a name+file.
        assert _read_names(tab.cfg_path) == ["x", "a", "b"]
        assert info_calls == []
    finally:
        root.destroy()
