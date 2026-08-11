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


# --- T-163: generated AHK must never close foreign wr*.ahk by wildcard ---------

def test_header_has_no_broad_ahk_close_logic():
    r"""The generated script must not carry window-title wildcard cleanup
    (^wr.*\.ahk + WinClose): basename/pattern similarity is NEVER authority
    to kill a process - wr_notes.ahk / wr_test.ahk belong to the user. AHK
    ownership and replacement is python-side, PID/identity-verified (T-163)."""
    cfg = {"mode": "general", "toggles": {}, "combos": [],
           "champions": {}, "afkfarm": {"enabled": False}}
    script, _ = generate_script(cfg)
    assert "WinGet, id, List" not in script
    assert "WinClose" not in script
    assert "wr.*" not in script  # no fuzzy filename identity anywhere
    assert "wr_notes" not in script  # nothing even names foreign scripts


def test_header_targets_no_window_by_title():
    """No WinClose / WinGet-List / fuzzy process targeting survives in the
    generated script - foreign wr_notes.ahk can never be closed by it. (The
    focus-watch WinExist for the GAME window is not a kill and is fine.)"""
    cfg = {"mode": "general", "toggles": {}, "combos": [],
           "champions": {}, "afkfarm": {"enabled": False}}
    script, _ = generate_script(cfg)
    assert "WinClose" not in script
    assert "WinGet, id, List" not in script


# --- T-164: AFK must never fabricate coordinates -------------------------------

def _afk_cfg(minimap=None, slots=None, enabled=True):
    return {
        "mode": "general",
        "toggles": {},
        "combos": [],
        "champions": {},
        "minimap": minimap or {},
        "afkfarm": {"enabled": enabled, "toggle_key": "F12",
                    "slots": slots or {}},
    }


def test_afk_enabled_zero_slots_no_cycle_no_fabricated_coords():
    cfg = _afk_cfg()
    script, _ = generate_script(cfg)
    assert "AFKFarmLogic:" not in script      # AFK block disabled
    assert "MouseMove, 116" not in script     # no invented Mid
    assert ", 293" not in script


def test_afk_enabled_invalid_coords_no_click_move():
    cfg = _afk_cfg(minimap={"top": {"x": 0, "y": 0, "trigger": "F1"}},
                   slots={"top": {"enabled": True}})
    script, _ = generate_script(cfg)
    assert "AFKFarmLogic:" not in script
    assert "SendEvent {Blind}{LButton}" not in script


def test_afk_enabled_valid_slots_unchanged():
    cfg = _afk_cfg(minimap={"top": {"x": 100, "y": 200, "trigger": "F1"}},
                   slots={"top": {"enabled": True}})
    script, _ = generate_script(cfg)
    assert "AFKFarmLogic:" in script
    assert "MouseMove, 100, 200, 0" in script


def test_validate_config_warns_when_afk_enabled_but_no_positions():
    cfg = _afk_cfg()
    from ahk_builder import validate_config
    warnings = validate_config(cfg)
    assert any("AFK" in w and "position" in w for w in warnings)


# --- T-165: AFK position availability must not depend on the minimap trigger --

def test_afk_slot_usable_with_valid_coords_and_empty_trigger():
    """The AFK cycle consumes slot x/y only - a manual minimap hotkey trigger
    is unrelated. Enabled slot + valid coords must stay usable (T-165)."""
    cfg = _afk_cfg(minimap={"top": {"x": 100, "y": 200, "trigger": ""}},
                   slots={"top": {"enabled": True}})
    script, _ = generate_script(cfg)
    assert "AFKFarmLogic:" in script
    assert "MouseMove, 100, 200, 0" in script


def test_validate_config_no_warning_with_coords_but_no_trigger():
    from ahk_builder import validate_config
    cfg = _afk_cfg(minimap={"top": {"x": 100, "y": 200, "trigger": ""}},
                   slots={"top": {"enabled": True}})
    warnings = validate_config(cfg)
    assert not any("no usable minimap positions" in w for w in warnings)


# --- T-166: AFK death detector must fail closed (ErrorLevel 2 = UNKNOWN) -------

def test_deathwatch_cfg_missing_file_returns_none(monkeypatch, tmp_path):
    """Bad/missing deathwatch config must NOT be silently replaced with
    hardcoded region/template - the detector is disabled instead (T-166)."""
    import ahk_builder
    monkeypatch.setattr(ahk_builder, "BASE", str(tmp_path))
    assert ahk_builder._deathwatch_cfg() is None


def test_deathwatch_cfg_corrupt_file_returns_none(monkeypatch, tmp_path):
    import ahk_builder
    (tmp_path / "deathwatch_config.json").write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(ahk_builder, "BASE", str(tmp_path))
    assert ahk_builder._deathwatch_cfg() is None


def test_deathwatch_cfg_missing_template_resource_returns_none(monkeypatch, tmp_path):
    import ahk_builder, json as _j
    valid = {
        "window_title": "", "poll_interval_sec": 0.4, "quickbuy_key": "Z",
        "quickbuy_presses": 5, "quickbuy_window_ms": 10.0, "shop_buffer_sec": 0.0,
        "timer_digits_region": [955, 143, 1035, 170], "restore_buffer_sec": 0.0,
        "max_death_wait_sec": 90.0, "digit_templates_dir": "d",
        "death_label_template": "templates/DOES_NOT_EXIST.png",
        "death_label_region": [900, 118, 1165, 145], "match_threshold": 0.75,
    }
    (tmp_path / "deathwatch_config.json").write_text(_j.dumps(valid), encoding="utf-8")
    monkeypatch.setattr(ahk_builder, "BASE", str(tmp_path))
    assert ahk_builder._deathwatch_cfg() is None


def test_deathwatch_cfg_valid_file_returns_region_and_template(monkeypatch, tmp_path):
    import ahk_builder, json as _j
    (tmp_path / "templates").mkdir()
    (tmp_path / "templates" / "death_label.png").write_bytes(b"x")
    valid = {
        "window_title": "", "poll_interval_sec": 0.4, "quickbuy_key": "Z",
        "quickbuy_presses": 5, "quickbuy_window_ms": 10.0, "shop_buffer_sec": 0.0,
        "timer_digits_region": [955, 143, 1035, 170], "restore_buffer_sec": 0.0,
        "max_death_wait_sec": 90.0, "digit_templates_dir": "d",
        "death_label_template": "templates/death_label.png",
        "death_label_region": [900, 118, 1165, 145], "match_threshold": 0.75,
    }
    (tmp_path / "deathwatch_config.json").write_text(_j.dumps(valid), encoding="utf-8")
    monkeypatch.setattr(ahk_builder, "BASE", str(tmp_path))
    region, template = ahk_builder._deathwatch_cfg()
    assert region == [900, 118, 1165, 145]
    assert template == "templates/death_label.png"


def test_generated_afk_death_check_is_fail_closed():
    """ErrorLevel 2 (detector could not search) must PAUSE AFK, never run the
    alive path - UNKNOWN != SAFE. ErrorLevel 1 = confident alive, 0 = dead."""
    cfg = _afk_cfg(minimap={"top": {"x": 100, "y": 200, "trigger": ""}},
                   slots={"top": {"enabled": True}})
    script, _ = generate_script(cfg)
    # 3-way ErrorLevel discrimination present:
    assert "else if (ErrorLevel = 1)" in script
    assert "if (ErrorLevel = 0)" in script
    # ErrorLevel 2 -> fail closed: force the dead/pause path
    fault = script[script.index("ImageSearch"):]
    assert "P_afk_WasDead := true" in fault


# --- T-167: autobuy must consume canonical engine validation ------------------

_BASE_DW = {
    "window_title": "Game", "poll_interval_sec": 0.4, "quickbuy_key": "Z",
    "quickbuy_presses": 5, "quickbuy_window_ms": 10.0, "shop_buffer_sec": 0.0,
    "timer_digits_region": [955, 143, 1035, 170], "restore_buffer_sec": 0.0,
    "max_death_wait_sec": 90.0, "digit_templates_dir": "d",
    "death_label_template": "templates/death_label.png",
    "death_label_region": [900, 118, 1165, 145], "match_threshold": 0.75,
    "autobuy_after_b": True, "buy_after_b_delay_sec": 6.5,
}


def _write_dw(tmp_path, monkeypatch, obj_or_text):
    import ahk_builder, json as _j
    text = obj_or_text if isinstance(obj_or_text, str) else _j.dumps(obj_or_text)
    (tmp_path / "deathwatch_config.json").write_text(text, encoding="utf-8")
    monkeypatch.setattr(ahk_builder, "BASE", str(tmp_path))


def _plain_cfg():
    return {"mode": "general", "toggles": {}, "combos": [],
            "champions": {}, "minimap": {}, "afkfarm": {"enabled": False}}


@pytest.mark.parametrize("mutate", [
    lambda d: d.__setitem__("quickbuy_key", "Ж"),          # Unicode key
    lambda d: d.__setitem__("quickbuy_key", "vkGG"),       # malformed vkNN
    lambda d: d.__setitem__("quickbuy_presses", 0),        # presses <= 0
    lambda d: d.__setitem__("buy_after_b_delay_sec", "abc"),  # wrong delay type
    lambda d: d.__setitem__("window_title", ""),           # empty window
])
def test_autobuy_requested_invalid_cfg_rejects(tmp_path, monkeypatch, mutate):
    dw = dict(_BASE_DW)
    mutate(dw)
    _write_dw(tmp_path, monkeypatch, dw)
    with pytest.raises(ValueError):
        generate_script(_plain_cfg())


def test_autobuy_requested_corrupt_json_rejects(tmp_path, monkeypatch):
    _write_dw(tmp_path, monkeypatch, "{corrupt")
    with pytest.raises(ValueError):
        generate_script(_plain_cfg())


def test_autobuy_valid_config_generates_block(tmp_path, monkeypatch):
    _write_dw(tmp_path, monkeypatch, _BASE_DW)
    script, _ = generate_script(_plain_cfg())
    assert "DoAutoBuy:" in script
    assert "vk5A" in script  # canonical quickbuy parser -> vk for Z


def test_autobuy_disabled_is_legitimate_omission(tmp_path, monkeypatch):
    dw = dict(_BASE_DW)
    dw["autobuy_after_b"] = False
    _write_dw(tmp_path, monkeypatch, dw)
    script, _ = generate_script(_plain_cfg())
    assert "DoAutoBuy:" not in script


def test_autobuy_missing_config_is_omission(tmp_path, monkeypatch):
    import ahk_builder
    monkeypatch.setattr(ahk_builder, "BASE", str(tmp_path))
    script, _ = generate_script(_plain_cfg())
    assert "DoAutoBuy:" not in script


def test_manual_aim_never_releases_move_hold():
    """Manual-aim ability keys NEVER release the move-hold - casting a skill
    must not stand the champion still, checkbox on or off. Combo flags are
    never touched either; only the 1-7/G stack and untoggle keys release."""
    for on in (True, False):
        cfg = {"mode": "general",
               "toggles": {**{"mouse_remap": True, "mouse_toggle_hold": True,
                              "manual_aim_block": True},
                           "release_toggle_on_keys": on},
               "combos": []}
        script, _ = generate_script(cfg)
        q = script[script.index("*sc010::"):]
        q = q[:q.index("return") + len("return")]
        assert "ReleaseMoveToggle" not in q
        assert "P_" not in q  # never touches combo flags


def test_item_keys_release_only_when_checkbox_on():
    """The 1-7/G release stack is gated on release_toggle_on_keys too."""
    base_toggles = {"mouse_remap": True, "mouse_toggle_hold": True}
    cfg_on = {"mode": "general", "toggles": {**base_toggles,
                                             "release_toggle_on_keys": True},
              "combos": []}
    script_on, _ = generate_script(cfg_on)
    g = script_on[script_on.index("~*sc022::"):]
    g = g[:g.index("return") + len("return")]
    assert "ReleaseMoveToggle" in g

    cfg_off = {"mode": "general", "toggles": {**base_toggles,
                                              "release_toggle_on_keys": False},
               "combos": []}
    script_off, _ = generate_script(cfg_off)
    assert "~*sc022::" not in script_off or "ReleaseMoveToggle" not in \
        script_off[script_off.index("~*sc022::"):script_off.index("~*sc022::") + 60]


def test_untoggle_keys_release_regardless_of_checkbox():
    """The configurable untoggle keys (a/v) release the move-hold whether or
    not release_toggle_on_keys is on, and never clear combo flags."""
    for on in (True, False):
        cfg = {"mode": "general",
               "toggles": {"mouse_remap": True, "mouse_toggle_hold": True,
                           "release_toggle_on_keys": on},
               "combos": []}
        script, _ = generate_script(cfg)
        a = script[script.index("~*sc01E::"):]
        a = a[:a.index("return") + len("return")]
        assert "ReleaseMoveToggle" in a
        assert "P_" not in a


def test_space_never_releases_move_or_stops_pvp():
    """Space is the attack key: it must NOT release the move-hold or touch the
    PVP combo - even with release_toggle_on_keys enabled. Attack while moving
    keeps the PVP hold and movement going."""
    config = {
        "mode": "general",
        "toggles": {"mouse_remap": True, "mouse_toggle_hold": True,
                    "release_toggle_on_keys": True, "space_spam": True},
        "combos": [],
    }
    script, _ = generate_script(config)
    space = script[script.index("*Space::"):]
    space = space[:space.index("return") + len("return")]
    assert "ReleaseMoveToggle" not in space
    assert "SendInput {Space}" in space


def test_release_move_toggle_configurable_keys_default_a_v():
    """Untoggle keys are user-configurable (toggles['untoggle_keys']), default
    a,v - they release the move-hold. 'b' is the dedicated recall-stop, NOT an
    untoggle key: pressing B kills combo spam + movement so the recall lands."""
    config = {
        "mode": "general",
        "toggles": {"mouse_remap": True, "mouse_toggle_hold": True},
        "combos": [],
    }
    script, _ = generate_script(config)
    # default untoggle keys a (sc01E) and v (sc02F) release the hold
    assert "~*sc01E::" in script  # a
    assert "~*sc02F::" in script  # v
    # b (sc030) is the recall-stop: it clears movement AND the combos
    b = script[script.index("~*sc030::"):]
    b = b[:b.index("return") + len("return")]
    assert "MoveRefs := 0" in b
    assert "ReleaseMoveToggle()" in b
    assert "CheckMovement()" in b


def test_release_move_toggle_custom_keys():
    config = {
        "mode": "general",
        "toggles": {"mouse_remap": True, "mouse_toggle_hold": True,
                    "untoggle_keys": "b,v,q"},
        "combos": [],
    }
    script, _ = generate_script(config)
    # 'b' is reserved for the recall-stop regardless of untoggle_keys
    assert "~*sc030::" in script  # recall-stop
    assert "MoveRefs := 0" in script[script.index("~*sc030::"):]
    # v and q join the untoggle stack
    assert "~*sc02F::" in script  # v
    assert "~*sc010::" in script  # q
    # a must be gone from the untoggle stack when the user drops it
    a_idx = script.find("~*sc01E::")
    if a_idx != -1:
        tail = script[a_idx:script.index("return", a_idx)]
        assert "ReleaseMoveToggle" not in tail


def test_release_move_toggle_empty_config_generates_no_stack():
    config = {
        "mode": "general",
        "toggles": {"mouse_remap": True, "mouse_toggle_hold": True,
                    "untoggle_keys": ""},
        "combos": [],
    }
    script, _ = generate_script(config)
    assert "~*sc01E::" not in script
    # the recall-stop on b is always generated, empty untoggle or not
    assert "~*sc030::" in script
    assert "MoveRefs := 0" in script


def test_b_recall_stops_pvp_combo_and_move():
    """Pressing B during a running PVP combo clears the combo flags and the
    movement hold, so the recall lands instead of the champion fighting on."""
    config = {
        "mode": "ryze",
        "toggles": {},
        "champions": {
            "ryze": {"trigger_pvp": "F15", "keys_pvp": "q,w,e",
                     "move_when_pressed_pvp": True},
        },
    }
    script, _ = generate_script(config)
    b = script[script.index("~*sc030::"):]
    b = b[:b.index("return") + len("return")]
    assert "P_ryze_pvp_Held := false" in b
    assert "Step_ryze_pvp := 0" in b
    assert "MoveRefs := 0" in b


def test_pvp_toggle_off_keeps_movement_until_lmb():
    """PVP toggle-off keeps the champion moving: when PVP's MoveRefs drops to
    zero the LMB move-hold is latched on, so the character keeps walking until
    the user clicks LMB again."""
    config = {
        "mode": "ryze",
        "toggles": {"mouse_remap": True, "mouse_toggle_hold": True},
        "champions": {
            "ryze": {"trigger_pvp": "F15", "keys_pvp": "q,w,e",
                     "move_when_pressed_pvp": True, "toggle_pvp": True},
        },
    }
    script, _ = generate_script(config)
    f15 = script[script.index("*F15::"):]
    f15 = f15[:f15.index("return") + len("return")]
    assert "MoveRefs := (MoveRefs > 0 ? MoveRefs - 1 : 0)" in f15
    assert "if (MoveRefs = 0) {" in f15
    assert "MoveToggle := true" in f15


def test_pvp_hold_release_keeps_movement():
    """Hold-mode PVP release latches the move-hold the same way: releasing the
    trigger keeps the champion walking until LMB click."""
    config = {
        "mode": "ryze",
        "toggles": {"mouse_remap": True, "mouse_toggle_hold": True},
        "champions": {
            "ryze": {"trigger_pvp": "F15", "keys_pvp": "q,w,e",
                     "move_when_pressed_pvp": True, "toggle_pvp": False},
        },
    }
    script, _ = generate_script(config)
    up = script[script.index("*F15 Up::"):]
    up = up[:up.index("return") + len("return")]
    assert "if (MoveRefs = 0) {" in up
    assert "MoveToggle := true" in up


def test_non_pvp_combos_do_not_latch_movement():
    """Wave/jungle combos keep their old stop-on-release behaviour - only the
    PVP slot latches movement after it ends."""
    config = {
        "mode": "ryze",
        "toggles": {"mouse_remap": True, "mouse_toggle_hold": True},
        "champions": {
            "ryze": {"trigger_wave": "F13", "keys_wave": "q,e",
                     "move_when_pressed_wave": True,
                     "trigger_pvp": "F15", "keys_pvp": "q,w,e",
                     "move_when_pressed_pvp": True, "toggle_pvp": True},
        },
    }
    script, _ = generate_script(config)
    up = script[script.index("*F13 Up::"):]
    up = up[:up.index("return") + len("return")]
    assert "MoveToggle := true" not in up
    assert "MoveRefs := (MoveRefs > 0 ? MoveRefs - 1 : 0)" in up


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
    # A combo bound to "a" collides with the ~*a untoggle handler (same sc01E
    # base in the same #IfWinActive context). validate_config never sees the
    # untoggle handler - only the post-generation scan does.
    config = _base_config()
    config["combos"].append({"trigger": "a", "keys": "q,e", "interval": 50})
    script, _ = generate_script(config)
    warnings = check_hotkey_conflicts(script)
    assert any("sc01E" in w and "conflict" in w for w in warnings)


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


# --- modifier-order conflict canonicalization (SAIT-005 / T-080) ---------------

def test_modifier_order_twins_flagged():
    # ^!sc010 and !^sc010 are the same chord to AutoHotkey (exit 2 Duplicate hotkey).
    warnings = check_hotkey_conflicts("^!sc010::\n  return\n!^sc010::\n  return")
    assert len(warnings) == 1
    assert "hotkey conflict" in warnings[0]


def test_modifier_order_triple_variants_flagged():
    warnings = check_hotkey_conflicts("^!+x::\n  return\n+^!x::\n  return")
    assert len(warnings) == 1


def test_lr_modifier_variants_stay_distinct():
    # <^ (LControl) vs >^ (RControl) are different physical keys - no conflict.
    warnings = check_hotkey_conflicts("<^sc010::\n  return\n>^sc010::\n  return")
    assert warnings == []


def test_generate_script_rejects_malformed_combo():
    cfg = {
        "mode": "general",
        "toggles": {"target_exe": "HD-Player.exe", "stop_key": "s"},
        "combos": [{"trigger": "F13", "keys": "q:", "interval": 50}],
    }
    with pytest.raises(ValueError):
        generate_script(cfg)

