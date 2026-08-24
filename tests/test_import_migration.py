"""W2-007 regression: explicit file import must normalize-then-validate.

T-CORE-013 fixed the same bug for the primary load (load_config) and .bak
recovery (_recover_corrupt_config): a valid LEGACY config (top-level ryze/xin
keys, or mode="xin") was being rejected by the modern validator BEFORE the
legacy migration could convert it. The explicit-import path (_do_import_file)
had the SAME defect: it called config_store.validate_config(imported) without
first calling _migrate_legacy_config.

Fix: _do_import_file now migrates before validating, consistent with the other
two ingress paths. These tests pin that behavior.
"""

import json

import pytest

import main as main_mod


def _new_importer(monkeypatch, saved, errors):
    """Build a bare VacWPlayer-shaped object whose _do_import_file can run
    headless: save/load are stubbed, the UI hooks are no-ops, and messageboxes
    are captured."""
    w = object.__new__(main_mod.VacWPlayer)
    w.config = {}
    w.status_lbl = type("S", (), {"config": lambda *a, **k: None})()
    monkeypatch.setattr(main_mod, "save_config",
                        lambda cfg, bypass_guard=False: saved.append(cfg) or True)
    monkeypatch.setattr(main_mod, "load_config", lambda: {})
    monkeypatch.setattr(main_mod.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(main_mod.messagebox, "showerror",
                        lambda title, msg: errors.append(msg))
    monkeypatch.setattr(w, "_rebuild_ui", lambda: None)
    return w


def test_import_legacy_xin_config_is_migrated_before_validate(monkeypatch, tmp_path):
    """A legacy config carrying top-level 'xin' data and mode='xin' must be
    accepted (migrated to xin_zhao) rather than rejected by the modern
    validator. Before W2-007 it was wrongly rejected at import time."""
    saved, errors = [], []
    w = _new_importer(monkeypatch, saved, errors)

    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({
        "mode": "xin",
        "xin": {"enabled_pvp": True, "toggle_pvp": True,
                "trigger_pvp": "F15,mbutton", "keys_pvp": "q,w,e"},
        "toggles": {}, "combos": [], "champions": {},
        "minimap": {}, "afkfarm": {},
    }), encoding="utf-8")

    w._do_import_file(str(legacy))

    assert errors == [], "legacy import should not be rejected: %s" % errors
    assert len(saved) == 1, "migrated legacy config must be saved"
    migrated = saved[0]
    # Migration folded the legacy xin block into champions.xin_zhao and remapped
    # the legacy mode string.
    assert migrated["mode"] == "xin_zhao"
    assert "xin_zhao" in migrated["champions"]
    assert migrated["champions"]["xin_zhao"]["keys_pvp"] == "q,w,e"


def test_import_legacy_ryze_config_is_migrated_before_validate(monkeypatch, tmp_path):
    saved, errors = [], []
    w = _new_importer(monkeypatch, saved, errors)

    legacy = tmp_path / "legacy_ryze.json"
    legacy.write_text(json.dumps({
        "mode": "ryze",
        "ryze": {"enabled_pvp": True, "toggle_pvp": False,
                 "trigger_pvp": "F14", "keys_pvp": "a,s,d"},
        "toggles": {}, "combos": [], "champions": {},
        "minimap": {}, "afkfarm": {},
    }), encoding="utf-8")

    w._do_import_file(str(legacy))

    assert errors == [], "legacy ryze import should not be rejected: %s" % errors
    assert len(saved) == 1
    migrated = saved[0]
    assert migrated["mode"] == "ryze"
    assert "ryze" in migrated["champions"]
    assert migrated["champions"]["ryze"]["keys_pvp"] == "a,s,d"


def test_import_modern_config_still_saved(monkeypatch, tmp_path):
    """Regression guard: a normal modern config still imports cleanly (the
    migration step must be a pass-through for non-legacy input)."""
    saved, errors = [], []
    w = _new_importer(monkeypatch, saved, errors)

    good = tmp_path / "good.json"
    good.write_text(json.dumps({
        "mode": "general", "toggles": {}, "combos": [],
        "champions": {}, "minimap": {}, "afkfarm": {}, "lang": "en",
    }), encoding="utf-8")

    w._do_import_file(str(good))

    assert errors == []
    assert len(saved) == 1
    assert saved[0]["mode"] == "general"


def test_import_garbage_still_rejected_before_save(monkeypatch, tmp_path):
    """The T-092 property must hold: structurally invalid imports are rejected
    BEFORE any save, even after the migrate-before-validate change."""
    saved, errors = [], []
    w = _new_importer(monkeypatch, saved, errors)

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    w._do_import_file(str(bad))

    assert saved == []
    assert errors
