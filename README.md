🇪🇪 [Eesti](README.ee.md) | 🇷🇺 [Русский](README.ru.md) | 🇺🇸 **English** | 👴 [Дед-Мод](README.ded.md) | 🇯🇵 [日本語](README.ja.md)

# VacWPlayer

**v0.3.0** — [Changelog](CHANGELOG.md)

One vintage-themed GUI over the whole Wild Rift toolkit: pedal combos, per-champion
rotations, death auto-minimize, and post-game auto-continue — a controllable "super
AHK" with a UI, no hand-editing scripts.

## Features

- **Main tab** — global input toggles (mouse remap, space spam, idle prevention, stop key,
  manual-aim pause, target exe) plus a General-mode custom combo list: add, delete,
  clear, bind trigger by keypress, reset to the legacy defaults.
- **Champions tab** — per-champion Wave / Jungle / PVP rotations. Sourced combos
  preloaded for Ryze, Xin Zhao, Yasuo, Master Yi, and others; placeholder combos
  for every champion in the Wild Rift roster — editable with preset slots.
- **Rotating Farm tab** — cycle through minimap positions, move + combo, repeat.
- **Death Watch / Auto Continue tabs** — drive the existing `deathwatch.py` /
  `autocontinue.py` engines (dry-run toggle, live status), each taking over cleanly
  with `--replace`.
- **Champion mode** — dropdown picks exactly one live combo set, so F13–F15 never collide.
- **Per-step delays** — `key:ms` syntax, e.g. `q,e:120,{Space}:200`.
- **Tray icon** — X hides to tray, engine keeps running; Quit stops everything.
- **Wiki** — architecture, config reference, tabs guide: `docs/wiki/`.

## Requirements

- Windows, Python 3.11, the project venv (`../venv`).
- AutoHotkey v1: `AutoHotkeyU64.exe` next to the app if present, else the standard install under `C:\Program Files\AutoHotkey\`.
- `pip install -r requirements.txt`.

## Run

Double-click **`VacWPlayer.vbs`** for a zero-console launch (hidden
window, app starts silently). Or run **`VacWPlayer.bat`** manually for
visible errors / `--check` diagnostics. Both auto-find the venv. Manually:

```
..\venv\Scripts\pythonw.exe main.pyw
```

Ryze assist auto-starts. Edit any tab, pick a champion, hit **Apply & Start**.

## Disclaimer

This tool automates game inputs (key presses, mouse clicks, screen detection).
**Using automation software with League of Legends: Wild Rift violates Riot Games'
Terms of Service.** Features like Rotating Farm, Idle Prevention, auto-accept/surrender,
and death automation may result in account suspensions or permanent bans. Use at your
own risk.

## Tests

```
python -m pytest tests/ -v
```

Requires pytest (`pip install pytest` or `pip install -r requirements.txt`).
Tests import non-GUI modules and verify all .py files compile cleanly.

## How it works

The GUI never hooks keys itself — it renders `wr_runtime.ahk` from `config.json` via
`ahk_generator.py` and launches AutoHotkey (Event mode, required by BlueStacks). Only
the runtime WE launch is tracked and killed by PID; other AHK scripts are left alone.
The old hand-written `wr.ahk` is retired automatically on start.

Three configs, one job each: `config.json` (combos, mode, toggles),
`deathwatch_config.json` (death detection), `autocontinue_config.json` (post-game
buttons). `wr_runtime.ahk` is generated — never hand-edit it.

## Combo syntax

Comma-separated keys. `{Space}`, `f`, letters. Ability letters q/w/e/r are Shift-cast
(self-cast) unless "Shift-cast" is off. Append `:ms` to a key for that step's own
delay; otherwise the combo interval applies. Hold the trigger pedal to cycle.
