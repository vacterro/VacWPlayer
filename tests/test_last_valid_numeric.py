"""W2-008 regression: last-valid numeric autosave semantics.

The numeric fields in MainTab / MinimapTab / AFKFarmTab are bound to GUI vars.
When the user is mid-edit (field emptied or partially typed) an autosave can
fire: the old code fell back to the CANONICAL DEFAULT on a parse failure, so a
transient invalid value silently overwrote the user's last good persisted value
with the default. Fix: each tab remembers the last *valid* value it persisted
and reuses it when the live var is incomplete, while leaving the raw edit text
in the field untouched. These tests pin that behavior.
"""

import tkinter as tk

import pytest

import tabs.main_tab as main_tab
import tabs.minimap_tab as minimap_tab
import tabs.afkfarm_tab as afkfarm_tab


def _root():
    pytest.importorskip("tkinter")
    r = tk.Tk()
    r.withdraw()
    return r


def test_main_tab_retains_last_valid_space_interval(monkeypatch):
    root = _root()
    try:
        tab = main_tab.MainTab(root, {"toggles": {"space_interval": 777,
                                                  "anti_afk_interval": 9000}})
        # User clears the field mid-edit -> invalid.
        tab.var_space_ms.set("")
        toggles = tab.get_toggles()
        # W2-008: last valid (777) retained, NOT the canonical default (128).
        assert toggles["space_interval"] == 777
        # A fresh valid value is persisted and becomes the new last-valid.
        tab.var_space_ms.set("250")
        assert tab.get_toggles()["space_interval"] == 250
    finally:
        root.destroy()


def test_main_tab_retains_last_valid_anti_afk_interval(monkeypatch):
    root = _root()
    try:
        tab = main_tab.MainTab(root, {"toggles": {"anti_afk_interval": 4321}})
        tab.var_afk_ms.set("garbage")
        toggles = tab.get_toggles()
        assert toggles["anti_afk_interval"] == 4321
        tab.var_afk_ms.set("1000")
        assert tab.get_toggles()["anti_afk_interval"] == 1000
    finally:
        root.destroy()


def test_afkfarm_retains_last_valid_duration_and_combo(monkeypatch):
    root = _root()
    try:
        tab = afkfarm_tab.AFKFarmTab(
            root, {"move_duration": 1234, "combo_interval": 456})
        # Both numeric fields emptied mid-edit.
        tab.var_duration.set("")
        tab.var_combo_ms.set("")
        data = tab.get_data()
        # W2-008: last valid retained, not AFKFARM_DEFAULTS.
        assert data["move_duration"] == 1234
        assert data["combo_interval"] == 456
        # Valid updates persist (and keep their clamping).
        tab.var_duration.set("700")
        assert tab.get_data()["move_duration"] == 700
        # Below the clamp floor still persists the floor, not the default.
        tab.var_combo_ms.set("3")
        assert tab.get_data()["combo_interval"] == 15
    finally:
        root.destroy()


def test_minimap_retains_last_valid_coords(monkeypatch):
    root = _root()
    try:
        saved = {"alpha": {"trigger": "f1", "x": 111, "y": 222}}
        tab = minimap_tab.MinimapTab(root, saved)
        # Grab the row for the seeded slot and blank its X field.
        key = next(k for k in tab._rows if tab.slots[k].get("x") == 111)
        assert tab.slots[key]["x"] == 111
        tab._rows[key]["x_var"].set("")
        data = tab.get_data()
        # W2-008: last valid coordinate retained, not reset to 0.
        assert data[key]["x"] == 111
        assert data[key]["y"] == 222
        # A valid edit then persists.
        tab._rows[key]["x_var"].set("333")
        assert tab.get_data()[key]["x"] == 333
    finally:
        root.destroy()


def test_minimap_last_valid_uses_loaded_config_value(monkeypatch):
    root = _root()
    try:
        # No saved override -> default slot value must be retained (not 0).
        tab = minimap_tab.MinimapTab(root, None)
        key = next(iter(tab._rows))
        loaded_x = tab.slots[key]["x"]
        tab._rows[key]["x_var"].set("abc")
        assert tab.get_data()[key]["x"] == loaded_x
    finally:
        root.destroy()
