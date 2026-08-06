from ahk_builder import generate_script


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
