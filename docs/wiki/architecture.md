# VacWPlayer — Architecture


## Overview

Single-window tkinter GUI (vintage Win95 theme) that manages the whole Wild Rift
automation toolkit: combo/pedal scripts, per-champion rotations, death auto-minimize,
post-game auto-continue, minimap clicks, AFK farm. The GUI never hooks keys itself —
it renders an AutoHotkey v1 script (`wr_runtime.ahk`) from JSON config and launches it.
Several standalone Python engines (deathwatch, autocontinue, accept) run as separate
subprocesses driven by their own config files.

## Process map

```
main.pyw  (TkinterDnD root, single instance via single_instance.py)
 ├── tabs/            UI layer — 10 tabs, all built at startup
 ├── theme.py / vintage_widgets.py   vintage look + pickers
 ├── locales.py       33-language UI strings (bundles in locales/*.json)
 ├── config.json      <-> main config (autosave debounce 300ms)
 ├── ahk_generator.py  generate wr_runtime.ahk, launch/stop AHK (PID-tracked)
 │   └── ahk_builder.py   script text assembly (the actual generator)
 ├── process_runner.py  subprocess wrapper for AHK
 ├── combo_browser.py / champ_picker.py   helper dialogs
 └── engines (own subprocesses, own configs):
      deathwatch.py      deathwatch_config.json  (py win32 API capture)
      autocontinue.py    autocontinue_config.json
      accept.py          accept_config.json
      surrender.py       surrender_config.json
```

## Lifecycle

- Entry: `main.pyw` → `single_instance.ensure_single_instance("wr_assistant", replace=True)`
  (kills previous holder PID); `atexit` registers `stop_everything()`.
- `VacWPlayer.__init__`: loads config, builds theme, creates `VintageNotebook`
  with all 10 tabs, restores last active tab, sets up tray.
- 100ms after start: `apply_and_start()` auto-runs (default combo set, Ryze, auto-starts).
- `_engine_watchdog` every 3000ms: if engine was supposed to run and
  `ahk_generator.is_running()` is false → regenerate + relaunch (auto-restart).
- Quit / close: `quit_app` → remember window pos, save config, `stop_everything()`
  (stops AHK + all tab engines) → destroy root.

## UI layer

- `VintageNotebook` + `_tab_specs`: 10 tabs —
  General (`main_tab`), Combos (`combo_tab`), Champions (`champion_tab`), Death
  (`death_tab`), Buy (`buy_tab`), Continue (`auto_tab`), Minimap (`minimap_tab`),
  Farm (`afkfarm_tab`), Accept (`accept_tab`), Surrender (`surrender_tab`).
- All tabs built upfront in `_build_all_tabs()` (no lazy loading); `_rebuild_ui`
  (config import) destroys all tabs, stops engines, reloads.
- Bottom bar: language combobox (33 languages), mode combobox (General + per-champion), export/import/
  backup config, hotkeys viewer, combo browser, status label, AHK running dot,
  Apply & Start / Stop.
- Config collected on demand: `collect_config()` pulls `get_data()`/`get_toggles()`
  from each loaded tab, stores `window.active_tab` + position.
- Auto-save: `<<AutoSave>>` virtual event → 300ms debounce → `_do_auto_save`.

## Config layer

- `config.json` (BASE dir): `mode`, `toggles` (TOGGLE_DEFAULTS), `combos`
  (LEGACY_COMBOS), `champions` (per-key: triggers/keys per slot), `minimap`
  (MINIMAP_DEFAULTS + `_order`), `afkfarm` (AFKFARM_DEFAULTS), `lang`, `window`.
  Volatile runtime state (window geometry, per-champion `enabled_*`/`toggle_*`)
  is split into the gitignored `config.local.json` on save and overlaid on load.
- `load_config()`: defaults merged over disk; migration from legacy `ryze`/`xin`
  top-level sections to `mode` + `champions`; stale `*_pixel` keys and
  `ryze_smart_logic` pruned.
- `save_config()`: indent-4 json write.
- Engines keep their own configs: `deathwatch_config.json`, `autocontinue_config.json`,
  `accept_config.json`, `surrender_config.json` — each with `load_config()`
  try/except (OSError/ValueError).
- Export/import (also via file drop), backup → `backups/config_YYYYMMDD_HHMMSS.json`.

## Engine layer

- `ahk_generator.generate_and_run(config)`: validates → `ahk_builder.generate_script`
  → writes `wr_runtime.ahk` → launches `AutoHotkeyU64.exe` with own PID tracking
  (`_find_our_pids` via parent-PID arg `%%1%%`, added runtime, not compile-time).
  Old hand-written `wr.ahk` retired automatically on start.
- `ahk_builder.generate_script`: header (CoordMode Client, SendInput mode,
  `#MaxHotkeysPerInterval`, per-window `WinActive` guards), autobuy timer, watchdog,
  hotkey blocks (combo pedals F13-F15 per mode, shift-cast q/w/e/r), master spammer
  (200ms idle / 15ms active dynamic timer), AFK farm logic, helper funcs.
- `process_runner.ProcessRunner`: polls subprocess output; `finally`-guaranteed
  `done` event (fix T-009).
- `poller_engine`: shared template-poller loop for accept/surrender/autocontinue
  (single-instance, parent watchdog, config mtime reload, window acquisition,
  template-match click).
- `key_blocker`: global KBDLL low-level hook (`ctypes`), blocks configured VK set,
  pedal blocking window (used by deathwatch mouse lock / death handling).
- `window_ctl`: DPI awareness, minimize/maximize/focus/click-at, `press_key_burst`.
- `capture`: BlueStacks window find, `grab`/`grab_region` via pywin32.
- `digit_reader`: white-text mask → column segmentation → template match (`read_number`),
  used by Buy tab gold reading.

## Standalone engines

Each is a `main(replace=False)` script; tabs launch them with `--replace` so the new
instance takes over cleanly. Dry-run toggle + live status in the tabs.

- `deathwatch.py`: screen-watches for death label (template match), minimizes game,
  locks mouse (`Ctrl+Shift+F8` unlock), blocks keys, restores on respawn.
- `autocontinue.py`: post-game buttons grouped by region, template-matched clicks.
- `accept.py`: match-accept screen, template-built buttons.
- `surrender.py`: surrender-vote buttons, template-built buttons.

## Supporting modules

- `champions.py`: roster + `default_for(name)` combo defaults + `slug()`.
- `combo_browser.py` / `champ_picker.py`: Toplevel pickers feeding Champions tab.
- `locales.py` (`Locale`): `set_lang`, `toggle`, `tr()`; 33 languages, bundles auto-loaded from `locales/*.json`.
- `theme.py`: `apply_base_theme`, `TOKENS`, `VintageButton/Label/Notebook`.
- `single_instance.py`: mutex-based single-instance with replace (kill old holder).
- `tests/`: `conftest.py` + `test_imports.py` — non-GUI import smoke + py_compile all.
- `tools/`: internal audit scripts (`ast_hunt.py`, `deep_hunt.py`, `meta_hunt.py`,
  `runtime_hunt.py`, `exec_hunt.py`, `git_hunt.py`, `record_burst.py`) — dev-only.

## Key invariants

1. `wr_runtime.ahk` is generated — never hand-edit.
2. Only the runtime WE launch is PID-tracked/killed; foreign AHK scripts untouched.
3. Engine subprocesses die on quit: `stop_everything()` stops AHK + all tabs.
4. Strict BlueStacks-only input: `WinActive` guards + SendInput for everything.
5. GUI threads never call tkinter directly from workers — `root.after(0, ...)`
   marshalling everywhere (`_apply_worker`, `_watchdog_worker`).