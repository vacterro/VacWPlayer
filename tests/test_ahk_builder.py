import pytest

from ahk_builder import check_hotkey_conflicts, generate_script, parse_steps


def test_v_and_a_keys_release_move_toggle():
    config = {
        "mode": "general",
        "toggles": {
            "mouse_remap": True,
            "mouse_toggle_hold": True,
            "manual_aim_block": True,
        },
        "combos": [],
    }
    script, _ = generate_script(config)
    # Check that ~*sc02F:: (v) and ~*sc01E:: (a) or sc_key variants are in the script calling ReleaseMoveToggle
    assert "ReleaseMoveToggle()" in script
    # Verify v and a in manual aim keys or release stack
    assert "*sc02F::" in script or "~*sc02F::" in script or "*v::" in script or "~*v::" in script
    assert "*sc01E::" in script or "~*sc01E::" in script or "*a::" in script or "~*a::" in script


def test_reset_state_untoggles_pvp_and_toggle_combos():
    config = {
        "mode": "ryze",
        "toggles": {},
        "champions": {
            "ryze": {
                "trigger_pvp": "F15",
                "keys_pvp": "q,w,e",
                "toggle_pvp": True,
            }
        },
    }
    script, _ = generate_script(config)
    # Ensure ResetState resets P_ryze_pvp_Held := false unconditionally
    assert "P_ryze_pvp_Held := false" in script


def _base_config():
    return {
        "mode": "general",
        "toggles": {
            "target_exe": "HD-Player.exe",
            "stop_key": "s",
            "manual_aim_block": True,
            "mouse_toggle_hold": True,
        },
        "combos": [],
        "minimap": {},
        "afkfarm": {"enabled": False},
    }


def test_no_conflicts_on_clean_render():
    script, _ = generate_script(_base_config())
    assert check_hotkey_conflicts(script) == []


def test_fixed_hotkey_collision_flagged():
    # A combo bound to "b" collides with the ~*b release-move handler
    # (same sc030 base in the same #IfWinActive context). validate_config
    # never sees the release handler - only the post-generation scan does.
    config = _base_config()
    config["combos"].append({"trigger": "b", "keys": "q,e", "interval": 50})
    script, _ = generate_script(config)
    warnings = check_hotkey_conflicts(script)
    assert any("sc030" in w and "conflict" in w for w in warnings)


def test_sc_code_and_letter_same_hotkey():
    warnings = check_hotkey_conflicts(
        "*sc030::\n  SendInput q\nreturn\n*b::\n  SendInput w\nreturn"
    )
    assert any("conflict" in w for w in warnings)


def test_guard_context_duplicates_not_flagged():
    # #If GuardCarry context legitimately re-registers the same hotkey
    # (E-120 carry guard) - must NOT be flagged.
    script = (
        "#IfWinActive ahk_exe HD-Player.exe\n"
        "*F13::\n  SendInput q\nreturn\n"
        "#If\n"
        '#If GuardCarry("F13")\n'
        "*F13::return\n"
        "*F13 Up::\n  Carry[\"F13\"] := false\nreturn\n"
        "#If\n"
    )
    assert check_hotkey_conflicts(script) == []


def test_modifier_distinct_not_conflict():
    warnings = check_hotkey_conflicts("*q::\n  return\n^q::\n  return")
    assert warnings == []


# --- parse_steps key validation (SAIT-001 / T-078) -----------------------------

def test_parse_steps_valid_keys():
    steps = parse_steps("q,e:120,{Space}:200", 50)
    assert steps == [("q", 50), ("e", 120), ("{Space}", 200)]


def test_parse_steps_accepts_letters_digits_fkeys_named():
    for k in ("q", "W", "5", "F13", "f24", "{Space}", "{Enter}", "{LButton}", "ц"):
        assert parse_steps(k, 50) == [(k, 50)], k


@pytest.mark.parametrize("keys", [
    "q:",           # trailing colon -> send-name {q:}
    "q:-100",       # negative delay -> send-name {q:-100}
    "ц:{Space}:50",  # cyrillic glued to named key
    "{Space",       # unterminated brace
    "Space}",       # stray close brace
    "q :e",         # space inside key
])
def test_parse_steps_rejects_invalid_keys(keys):
    with pytest.raises(ValueError):
        parse_steps(keys, 50)


def test_parse_steps_comma_only_is_empty():
    assert parse_steps(",,,", 50) == []


def test_generate_script_rejects_malformed_combo():
    cfg = {
        "mode": "general",
        "toggles": {"target_exe": "HD-Player.exe", "stop_key": "s"},
        "combos": [{"trigger": "F13", "keys": "q:", "interval": 50}],
    }
    with pytest.raises(ValueError):
        generate_script(cfg)

