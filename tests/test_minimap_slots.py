"""MinimapTab slot logic unit tests (dynamic add/remove/reorder, T-046)."""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from tabs.minimap_tab import MinimapTab, MINIMAP_DEFAULTS, DEFAULT_ORDER


def _tab(**attrs):
    t = MinimapTab.__new__(MinimapTab)
    for k, v in attrs.items():
        setattr(t, k, v)
    t._add_row = lambda *a, **k: None
    t._auto_save = lambda *a, **k: None
    t._rebuild_form = lambda: None
    return t


# --- _merge_slots ----------------------------------------------------------

def test_merge_defaults_when_no_saved():
    t = _tab(_loaded_order=None)
    t.slots = t._merge_slots(None)
    assert set(t.slots) == set(MINIMAP_DEFAULTS)
    assert t._loaded_order is None


def test_merge_preserves_custom_slots_and_values():
    saved = {
        "_order": ["top", "custom_1"],
        "top": {"trigger": "F1", "x": 11, "y": 12},
        "custom_1": {"trigger": "F23", "x": 100, "y": 200},
    }
    t = _tab(_loaded_order=None)
    t.slots = t._merge_slots(saved)
    assert t.slots["top"] == {"trigger": "F1", "x": 11, "y": 12}
    assert t.slots["custom_1"] == {"trigger": "F23", "x": 100, "y": 200}
    # defaults not present in saved still merged in
    assert "mid" in t.slots and "bot" in t.slots
    assert t._loaded_order == ["top", "custom_1"]


def test_merge_partial_custom_overrides_defaults():
    saved = {"top": {"trigger": "F9"}}  # only trigger changed
    t = _tab(_loaded_order=None)
    t.slots = t._merge_slots(saved)
    assert t.slots["top"]["trigger"] == "F9"
    assert t.slots["top"]["x"] == MINIMAP_DEFAULTS["top"]["x"]
    assert t.slots["top"]["y"] == MINIMAP_DEFAULTS["top"]["y"]


def test_merge_skips_order_key_and_non_dict():
    saved = {"_order": ["x"], "junk": "not-a-dict", "top": {"trigger": "F5"}}
    t = _tab(_loaded_order=None)
    t.slots = t._merge_slots(saved)
    assert "junk" not in t.slots
    assert "top" in t.slots


# --- _resolve_order --------------------------------------------------------

def test_resolve_order_uses_loaded_order():
    slots = {k: dict(v) for k, v in MINIMAP_DEFAULTS.items()}
    slots["custom_1"] = {"trigger": "F23", "x": 1, "y": 2}
    t = _tab(slots=slots, _loaded_order=["custom_1", "top"])
    order = t._resolve_order()
    assert order[0] == "custom_1"
    assert order[1] == "top"
    # missing from loaded order appended at end
    assert set(order) == set(slots)


def test_resolve_order_default_when_no_loaded():
    slots = {k: dict(v) for k, v in MINIMAP_DEFAULTS.items()}
    slots["custom_1"] = {"trigger": "F23", "x": 1, "y": 2}
    t = _tab(slots=slots, _loaded_order=None)
    order = t._resolve_order()
    assert order[:len(DEFAULT_ORDER)] == DEFAULT_ORDER
    assert order[-1] == "custom_1"


def test_resolve_order_appends_new_slots():
    slots = {k: dict(v) for k, v in MINIMAP_DEFAULTS.items()}
    slots["custom_1"] = {"trigger": "F23", "x": 1, "y": 2}
    t = _tab(slots=slots, _loaded_order=["top"])
    order = t._resolve_order()
    assert order[0] == "top"
    assert "custom_1" in order


# --- add_slot key generation ----------------------------------------------

def test_add_slot_generates_unique_keys():
    t = _tab(_custom_counter=0, slots={}, _rows={})
    t.add_slot()
    assert "custom_1" in t.slots
    t.add_slot()
    assert "custom_2" in t.slots


def test_remove_slot_drops_key():
    t = _tab(_custom_counter=1, slots={"custom_1": {"trigger": "F23", "x": 1, "y": 2}},
             _rows={"custom_1": {"name_entry": None, "name_lbl": None, "trigger_var": None,
                                 "x_var": None, "y_var": None, "remove_btn": None}},
             _loaded_order=None)
    t.remove_slot("custom_1")
    assert "custom_1" not in t.slots


def test_get_data_includes_all_slots_and_order():
    slots = {k: dict(v) for k, v in MINIMAP_DEFAULTS.items()}
    slots["custom_1"] = {"trigger": "F23", "x": 1, "y": 2}
    t = _tab(slots=slots, _rows={}, _loaded_order=None)
    data = t.get_data()
    assert data["_order"] == DEFAULT_ORDER + ["custom_1"]
    assert data["custom_1"] == {"trigger": "F23", "x": 1, "y": 2}
    assert data["top"] == slots["top"]
