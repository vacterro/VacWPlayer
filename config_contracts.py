"""UI-neutral config contracts.

Canonical home of TOGGLE_DEFAULTS (PERF-005). Headless consumers
(config_store validation) and the GUI (tabs.main_tab) import the SAME object
from here, so the toggle contract is single-sourced without dragging
tkinter/theme/locales (and all 33 locale JSON files) into CLI-only imports.
"""

TOGGLE_DEFAULTS = {
    "mouse_remap": True,
    "mouse_move_instead_hold": False,
    "mouse_toggle_hold": False,
    "release_toggle_on_keys": False,
    "untoggle_keys": "a,v",
    "keep_movement_on_death": False,
    "rmb_hold_pvp": True,
    "space_spam": True,
    "space_interval": 128,
    "anti_afk_hotkey": True,
    "anti_afk_interval": 5000,
    "stop_key": "s",
    "manual_aim_block": True,
    "guard_outside_game": True,
    "cursor_outside_mode": "pause",
    "exit_when_bs_gone": True,
    "target_exe": "HD-Player.exe",
}
