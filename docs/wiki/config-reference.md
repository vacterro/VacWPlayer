# VacWPlayer — Configuration Reference


All configs are JSON in the project root (`BASE` = script dir). The GUI owns
`config.json`; each standalone engine owns its own file. None of them tolerate
malformed JSON — engine `load_config()` prints FATAL and exits 1.

## config.json (GUI, main)

Written by `save_config()` on: Apply & Start, auto-save (300ms debounce after any
change), lang toggle, quit. Loaded by `load_config()` with deep-merge over defaults
(`main.pyw:default_config()`); legacy `ryze`/`xin` sections auto-migrated to
`mode` + `champions`.

**Runtime state lives in `config.local.json` (gitignored).** Window geometry
(`window.active_tab`, `window.position`) and per-champion checkbox flags
(`enabled_*` / `toggle_*`) are split out on save and overlaid back on load, so
`config.json` only carries settings worth committing. Missing or corrupt
`config.local.json` is silently ignored — it is expendable by design.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `mode` | str | `"ryze"` | Active combo set: `general` or champion key (slug) |
| `toggles` | object | TOGGLE_DEFAULTS | Global input toggles (see below) |
| `combos` | array | LEGACY_COMBOS | General-mode custom combo list |
| `champions` | object | per-champion defaults | Per-champion trigger/keys per slot |
| `minimap` | object | MINIMAP_DEFAULTS | Minimap click slots + `_order` |
| `afkfarm` | object | AFKFARM_DEFAULTS | AFK farm settings |
| `lang` | str | `"ru"` | UI language code, any of 33 (e.g. `ru`, `en`, `ja`, `et`) |
| `window` | object | `{"active_tab": 0}` | Last tab index + window position |
| `auto_accept` | object | `{"enabled": false}` | Auto-accept switch (Main tab) |

### toggles (main_tab.py:TOGGLE_DEFAULTS)

| Key | Default | Meaning |
|---|---|---|
| `mouse_remap` | true | Mouse remap active |
| `mouse_toggle_hold` | false | LMB toggles move hold (click again to release) |
| `release_toggle_on_keys` | false | 1-7,G release the move-hold when pressed |
| `untoggle_keys` | `"a,v"` | Comma-separated keys that release the move-hold; `b` is reserved for the recall-stop |
| `space_spam` | true | Space spamming (attack — never releases the hold) |
| `space_interval` | 128 | ms between space presses |
| `anti_afk_hotkey` | true | Ctrl+G anti-AFK toggle in game |
| `anti_afk_interval` | 5000 | ms |
| `stop_key` | `"s"` | Global stop key |
| `manual_aim_block` | true | Manual-aim pause |
| `guard_outside_game` | true | Mute a carried-over pedal hold once the game stops being active |
| `target_exe` | `"HD-Player.exe"` | Emulator process target (WinActive guard) |

`guard_outside_game` is deliberately **not** a blanket block — the pedal stays
usable outside the game. Each in-game F-key trigger sets `Carry["<base>"]` on
its key-down, and the generator emits a matching `#If GuardCarry("<base>")`
variant. That variant only exists for a press that began inside the game and is
still physically held, i.e. the death-minimize case where a foot never left the
pedal and its auto-repeat would otherwise rain into whatever app is now in
front. Releasing the pedal clears `Carry`, so the very next press outside the
game reaches Windows untouched. `FocusWatch` also clears any `Carry` entry whose
key is no longer physically down, so a lost key-up can never leave the pedal
dead.

F13–F24 are guarded with any modifier (`*F13`); F1–F12 only in the exact
modifier combination configured, so system chords like Alt+F4 are never
shadowed. Letter/digit triggers are never guarded — they have to stay typeable.

### combos (General mode)

`[{"trigger": "F13", "keys": "q,e,{Space}", "interval": 50, "shift": true}, ...]`
— keys: comma-separated; `{Space}` braces for specials; `:ms` per-step delay;
`shift` = shift-cast q/w/e/r.

### champions (per-champion)

Keyed by slug (`ryze`, `xin_zhao`, ...). Fields per slot (`wave`/`jungle`/`pvp`):
`trigger_<slot>` (F13/F14/F15 pedals), `keys_<slot>` (comma-separated), optional
`ignore_npc_keys_<slot>`, plus `interval` (ms), `use_shift` (bool, default true),
`qwer_as_uiop` (bool), `display_name`, and `presets_<slot>` arrays (3 preset slots
`{keys, name}` each). On load, stale `*_pixel` keys and `ryze_smart_logic` are pruned.

### minimap (minimap_tab.py:MINIMAP_DEFAULTS)

Per slot: `{"trigger": "!F9", "x": 64, "y": 137}` — x/y are click coordinates in the
game window (drag-registered). Slots: `top`, `mid`, `bot`, `top_deep`, `mid_deep`,
`bot_deep`, `base`, `enemy_base`; `_order` keeps display order. Empty trigger =
disabled slot.

### afkfarm (afkfarm_tab.py:AFKFARM_DEFAULTS)

`enabled` (default true), `toggle_key` (F23), `move_duration` (ms), `follow_cursor`,
`combo_keys`, `combo_interval` (ms), `slots` (list of minimap slot keys to cycle).

## deathwatch_config.json (deathwatch.py)

| Key | Default (disk) | Meaning |
|---|---|---|
| `monitor_enabled` | true | Run death monitor |
| `window_title` | `"BlueStacks App Player"` | Game window to watch |
| `poll_interval_sec` | 0.4 | Screen poll rate |
| `shop_buffer_sec` | 0.0 | Delay after death before acting |
| `restore_buffer_sec` | 2.0 | Delay before restore on respawn |
| `match_threshold` | 0.75 | Template match score cut |
| `death_label_region` | `[900,118,1165,145]` | x1,y1,x2,y2 of death label |
| `timer_digits_region` | `[955,143,1035,170]` | Respawn timer digits |
| `death_label_template` | `"templates/death_label.png"` | Relative to BASE |
| `digit_templates_dir` | `"templates/digits"` | digit_reader templates |
| `max_death_wait_sec` | 90.0 | Give up waiting after |
| `quickbuy_key` | `"Z"` | Buy spam key on death |
| `quickbuy_presses` | 5 | Press count |
| `quickbuy_window_ms` | 10.0 | Press interval |
| `blocked_keys` | `["F13","F14","F15"]` | Keys blocked while dead (key_blocker) |
| `pedal_block_sec` | 1.0 | Pedal block duration |
| `switch_to_work_window` | false | Switch to work window (e.g. this GUI) |
| `work_window_title` | `"VacWPlayer"` | |
| `click_mid_on_resurrect` | false | Click minimap mid on respawn |
| `lock_window_resurrect` | false | Lock window until respawn |
| `autobuy_after_b` | false | Auto-buy after recalling (B) |
| `buy_after_b_delay_sec` | 6.5 | |
| `autobuy_then_mid` | false | Auto-buy then click mid |
| `autobuy_then_mid_delay_sec` | 0.5 | |
| `controlsend_z` | false | Use ControlSend instead of SendInput for buy |

## autocontinue_config.json (autocontinue.py)

| Key | Default (disk) | Meaning |
|---|---|---|
| `monitor_enabled` | false | Run post-game monitor |
| `window_title` | `"BlueStacks App Player"` | |
| `poll_interval_sec` | 0.6 | |
| `click_cooldown_sec` | 2.5 | Min time between clicks |
| `buttons` | 3 entries | Click targets, see below |

`buttons[]`: `{"name", "region": [x1,y1,x2,y2], "template": "templates/buttons/<name>.png",
"threshold": 0.85}` — grouped by region (`group_by_region`), matched with
`cv2.matchTemplate` CCOEFF_NORMED, clicked via `window_ctl.click_at`.

## accept_config.json (accept.py)

| Key | Default (disk) | Meaning |
|---|---|---|
| `monitor_enabled` | false | Run accept poller |
| `window_title` | `"BlueStacks App Player"` | |
| `poll_interval_sec` | 1.0 | |
| `click_cooldown_sec` | 3.0 | |
| `templates` | `[]` | `{file, region, threshold}` entries, built via `build_templates` |

Uses `PrintWindow` capture — works even when game window is behind others.

## surrender_config.json (surrender.py)

| Key | Default (disk) | Meaning |
|---|---|---|
| `monitor_enabled` | true | Run surrender poller |
| `window_title` | `""` | Game window to watch (picked via window picker) |
| `poll_interval_sec` | 5.0 | |
| `click_cooldown_sec` | 3.0 | Min time between clicks |
| `auto_accept` | false | Click Accept (`true`) or Decline (`false`) on surrender prompt |
| `templates` | Accept/Decline entries | `{name, file, threshold}` entries, built via `build_templates` |

Same capture/`build_templates` machinery as `accept_config.json`.

## Engine behavior notes

- `--replace` flag: kills the previous instance of the same engine (single_instance)
  so a fresh instance takes over cleanly (tab UI passes it on start).
- All engines print FATAL + `SystemExit(1)` on missing/corrupt config — no fallback.
- `templates/` tree (death label, digits, buttons) is relative to project root.