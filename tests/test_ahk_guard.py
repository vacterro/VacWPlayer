"""ahk_builder guard/carry unit tests (E-120 carry-guard logic)."""

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import ahk_builder as ab


def _cfg(combos=(), minimap=None, afk_k=None, toggles=None):
    return {
        "mode": "general",
        "toggles": dict(toggles or {"target_exe": "HD-Player.exe"}),
        "combos": list(combos),
        "minimap": minimap or {},
        "afkfarm": {"enabled": bool(afk_k), "toggle_key": afk_k or ""},
    }


# --- _guard_variant --------------------------------------------------------

@pytest.mark.parametrize("trig,expected", [
    ("F13", ("*F13", "F13")),
    ("F14", ("*F14", "F14")),
    ("F24", ("*F24", "F24")),
    ("f15", ("*f15", "f15")),          # case preserved through variant
    ("!F13", ("*F13", "F13")),         # F13-F24 -> wildcard, mods dropped
    ("^+F13", ("*F13", "F13")),
    ("F9", ("F9", "F9")),              # F1-F12 keep exact modifier list
    ("!F9", ("!F9", "F9")),
    ("^!F9", ("^!F9", "F9")),
    ("~F9", ("F9", "F9")),             # '~' pass-through stripped from guard
    ("$F9", ("F9", "F9")),
])
def test_guard_variant(trig, expected):
    assert ab._guard_variant(trig) == expected


@pytest.mark.parametrize("trig", ["", "q", "e", "1", "9", "{Space}", "{Enter}", "!q"])
def test_guard_variant_none_for_typeable(trig):
    assert ab._guard_variant(trig) is None


# --- _base_key -------------------------------------------------------------

@pytest.mark.parametrize("trig,base", [
    ("F13", "F13"), ("!F9", "F9"), ("^+F13", "F13"),
    ("*F15", "F15"), ("~$F16", "F16"), ("q", "q"), ("", ""),
])
def test_base_key(trig, base):
    assert ab._base_key(trig) == base


# --- _guarded_triggers -----------------------------------------------------

def test_guarded_triggers_collects_combos_minimap_afk():
    # combos arrive pre-processed by _active_combos, carrying a `triggers` list
    combos = [
        {"triggers": ["F13"], "keys": "q,e"},
        {"triggers": ["F14", "F15"], "keys": "w"},   # multi-trigger combo
        {"triggers": ["!F9"], "keys": "e"},          # F9 kept with mods
        {"triggers": ["q"], "keys": "r"},            # typeable -> never guarded
    ]
    minimap = {"top": {"trigger": "F16", "x": 1, "y": 2}, "_order": ["top"]}
    guards = ab._guarded_triggers({"guard_outside_game": True},
                                  combos, minimap, "F17")
    assert guards == [("*F13", "F13"), ("*F14", "F14"), ("*F15", "F15"),
                      ("!F9", "F9"), ("*F16", "F16"), ("*F17", "F17")]


def test_guarded_triggers_dedupes_variants():
    combos = [{"trigger": "F13", "keys": "q"}, {"trigger": "*F13", "keys": "w"}]
    guards = ab._guarded_triggers({"guard_outside_game": True}, combos, {}, None)
    assert guards == [("*F13", "F13")]


def test_guarded_triggers_skips_minimap_order_and_non_dict():
    minimap = {"_order": ["top"], "top": {"trigger": "F13", "x": 1, "y": 2}}
    guards = ab._guarded_triggers({"guard_outside_game": True},
                                  [], minimap, None)
    assert guards == [("*F13", "F13")]


def test_guarded_triggers_empty_when_guard_off():
    combos = [{"trigger": "F13", "keys": "q"}]
    assert ab._guarded_triggers({"guard_outside_game": False}, combos, {}, "F14") == []


def test_guarded_triggers_default_on_when_key_missing():
    combos = [{"trigger": "F13", "keys": "q"}]
    guards = ab._guarded_triggers({}, combos, {}, None)
    assert guards == [("*F13", "F13")]


# --- _carry_set ------------------------------------------------------------

@pytest.mark.parametrize("trig,value,expected", [
    ("F13", True, 'Carry["F13"] := true'),
    ("!F9", False, 'Carry["F9"] := false'),
    ("", True, None),
])
def test_carry_set(trig, value, expected):
    assert ab._carry_set(trig, value) == expected


# --- guard emission in generated script ------------------------------------

def test_script_emits_carry_set_and_up_clear():
    script, _ = ab.generate_script(_cfg(combos=[{"trigger": "F13", "keys": "q,e"}]))
    assert 'Carry["F13"] := true' in script     # on press
    assert 'Carry["F13"] := false' in script    # on Up + guard block


def test_script_emits_guardcarry_function_and_contexts():
    script, _ = ab.generate_script(
        _cfg(combos=[{"trigger": "F13", "keys": "q"}],
             minimap={"top": {"trigger": "F14", "x": 1, "y": 2}}))
    assert 'GuardCarry(k) {' in script
    assert 'return Carry[k] ? true : false' in script
    assert '#If GuardCarry("F13")' in script
    assert '#If GuardCarry("F14")' in script
    # guard blocks swallow the press, clear Carry on Up
    assert '*F13::return' in script
    assert '*F14::return' in script


def test_script_focus_watch_emits_stale_carry_sweep():
    script, _ = ab.generate_script(_cfg(combos=[{"trigger": "F13", "keys": "q"}]))
    assert 'Loop, Parse, % "F13", `,' in script
    assert 'if (Carry[A_LoopField] && !GetKeyState(A_LoopField, "P"))' in script
    assert 'Carry[A_LoopField] := false' in script


def test_script_no_guard_when_toggle_off():
    script, _ = ab.generate_script(
        _cfg(combos=[{"trigger": "F13", "keys": "q"}],
             toggles={"target_exe": "HD-Player.exe", "guard_outside_game": False}))
    assert 'GuardCarry(' not in script
    assert 'Carry["F13"]' not in script


def test_script_typeable_trigger_not_guarded():
    script, _ = ab.generate_script(_cfg(combos=[{"trigger": "q", "keys": "w"}]))
    assert 'GuardCarry(' not in script


def test_guard_dedupe_in_generated_script():
    # Same base via different modifier spellings -> one guard context.
    script, _ = ab.generate_script(
        _cfg(combos=[{"trigger": "F13", "keys": "q"}, {"trigger": "*F13", "keys": "w"}]))
    assert script.count('#If GuardCarry("F13")') == 1


def _pvp_cfg(toggles=None):
    cfg = _cfg(toggles=toggles)
    cfg["mode"] = "ryze"
    cfg["champions"] = {"ryze": {
        "trigger_pvp": "F15",
        "keys_pvp": "q,w,e",
        "move_when_pressed_pvp": True,
        "toggle_pvp": False,
    }}
    return cfg


def _rmb_down_handler(script):
    """The *RButton:: down-handler body, from hotkey to the matching Up."""
    idx = script.index("*RButton::")
    end = script.index("*RButton Up::", idx)
    return script[idx:end]


def _assert_rmb_guarded(script):
    assert 'global RMB_Pass := false' in script
    handler = _rmb_down_handler(script)
    # cursor-outside guard must gate the remap, symmetric to LMB
    assert '!MouseIsOver("ahk_exe HD-Player.exe")' in handler
    assert 'RMB_Pass := true' in handler
    assert 'SendEvent {RButton down}' in handler
    # bypass runs before the remap click
    assert handler.index("!MouseIsOver") < handler.index("SendInput {LButton down}")
    # Up releases the passed-through click before any PVP combo logic
    assert 'if (RMB_Pass) {' in script
    assert 'SendInput {RButton up}' in script


def test_rmb_hold_pvp_guarded_like_lmb():
    # RMB-hold drives the PVP combo: cursor outside the game must pass the
    # real right-click through (like LMB does) instead of remapping it into
    # an LButton click that lands on the desktop.
    _assert_rmb_guarded(ab.generate_script(_pvp_cfg())[0])


def test_rmb_plain_remap_guarded_when_rmb_hold_off():
    _assert_rmb_guarded(ab.generate_script(_cfg(toggles={
        "target_exe": "HD-Player.exe",
        "rmb_hold_pvp": False,
    }))[0])
