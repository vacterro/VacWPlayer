# WildRiftAssistant — Tabs Guide


The main window: 9-tab `VintageNotebook` + bottom bar. All tabs are built at
startup (no lazy loading); each tab auto-saves its settings (debounced 300ms)
into `config.json` or its engine config.

## General (tabs/main_tab.py) — global input + auto-accept

- Toggles: Mouse remap (LMB=move hold, RMB=tap), Space spam while held, Anti-AFK
  (Ctrl+G toggles in game), Manual q/w/e/r/d/f pauses combos.
- Numeric: Stop key (default `s`), Spc ms (space interval), AFK ms (anti-AFK
  interval), Exe (target emulator, dropdown from `EMULATOR_EXES` + manual).
- Auto-accept switch (writes `config.auto_accept`; engine `accept.py`).
- Notes: `detect_running_emulators()` lists live emulator processes.

## Combos (tabs/combo_tab.py) — General-mode custom combos

- List of custom combos: add, delete, clear, reset to legacy defaults (`LEGACY_COMBOS`).
- Editor per combo: Trigger (bind by keypress), Keys, Interval (ms),
  Shift-cast q/w/e/r checkbox.
- Syntax hint: `key:ms` per-step delay, e.g. `q,e:120,{Space}:200`.
- Active only when mode = General; F13–F15 collide with champion mode by design
  (one live combo set at a time).

## Champions (tabs/champion_tab.py) — per-champion rotations

- Champion dropdown (roster from `champions.py`), add/remove champion.
- Three slots — Wave / Jungle / PVP — each: trigger (F13/F14/F15 pedals), keys
  (comma list), optional ignore-NPC keys, and 3 named presets each.
- Interval (ms), Shift modifier / "Interpret QWER as UIOP" checkboxes
  (shift-cast and BlueStacks U/I/O/P keybind mapping).
- Mode box on bottom bar picks exactly one live champion set.

## Death (tabs/death_tab.py) — deathwatch engine

- Drives `deathwatch.py` subprocess (launched with `--replace`): monitor enable,
  poll interval, match threshold, death label region + template, timer digits
  region, max wait, restore buffer, shop buffer.
- Quick-buy on death: key, presses, window (ms) — with **Block keys** field
  (keys blocked while dead, `key_blocker.py`), pedal block sec.
- Work-window switching, click-mid / lock-window on resurrect.
- Dry-run toggle + live status; `stop_all()` on quit/rebuild.

## Buy (tabs/buy_tab.py) — auto-buy after recall

- Quick-buy key / presses / window (ms).
- Auto-buy after B: delay (s); auto-buy then mid: delay (s).
- Reads gold via `digit_reader` (white-text mask + template match) to gate buys.
- Writes into `deathwatch_config.json` (shared with Death tab).

## Continue (tabs/auto_tab.py) — autocontinue engine

- Drives `autocontinue.py` (`--replace`): monitor enable, poll interval, click
  cooldown; shows the buttons it clicks (victory/continue screens grouped by
  region). Dry-run toggle + live status.

## Minimap (tabs/minimap_tab.py) — click-to-move hotkeys

- 8 slots (Top/Mid/Bot, Top/Mid/Bot Deep, Base, Enemy Base): Name, Hotkey
  (bind via `BindButton` keypress), X, Y (click coordinates in game window;
  "Click on lane = move there in game").
- Rows reorderable; drag-register X/Y; empty trigger = slot disabled.
- Writes `config.minimap` incl. `_order`.

## Farm (tabs/afkfarm_tab.py) — AFK farm

- Toggle key (default F23), move duration (ms), follow cursor, combo keys,
  combo interval (ms), slots list (minimap slots to cycle). Runs in AHK
  (`_gen_afk_farm`): walks slots, holds combo, dynamic timer.
- Locale-aware labels.

## Accept (tabs/accept_tab.py) — auto-accept

- Drives `accept.py` (`--replace`): poll (s), cooldown (s), button templates
  list (name/region/template/threshold). Prints match status messages.
- Templates built from `accept_config.json` via `build_templates`.

## Bottom bar (main.pyw)

- Language combobox (33 languages, native names), mode combobox (General + champions), Export / Import
  (also JSON file drop onto window) / Backup config, Hotkeys viewer, Combo
  browser (opens `combo_browser.py`), status label, AHK running dot
  (green/red), **Apply & Start**, **Stop**, tray icon (Show / Apply & Start /
  Stop engine / Quit).
- Auto-starts on launch (100ms); engine watchdog auto-restarts every 3s if
  the runtime died while `_engine_should_run` is true.