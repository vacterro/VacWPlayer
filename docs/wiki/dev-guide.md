# VacWPlayer — Developer Guide


## Setup

- Windows + Python 3.11; project venv at `../venv` (sibling of project dir).
- Launcher prefers system Python 3.11 (`%LOCALAPPDATA%\Programs\Python\Python3*\pythonw.exe`)
  over the venv — the venv `pythonw.exe` is a stub wrapper that re-spawns the
  system interpreter and creates duplicate GUI/engine processes.
- `pip install -r requirements.txt` — mss, opencv-python, numpy, pywin32,
  pystray, pillow, pytest.
- AutoHotkey v1: `AutoHotkeyU64.exe` next to the app if present, else the
  standard install under `C:\Program Files\AutoHotkey\` — runtime dependency,
  never pip-installable. See `ahk_generator.find_ahk_exe()`.
- Git repo: `github.com/vacterro/VacWPlayer`, branch `main`, tagged
  releases (`v0.1.0`+).

## Run

```
VacWPlayer.bat   (or: pythonw.exe main.pyw with system Python 3.11)
```

- Single instance enforced (`single_instance.ensure_single_instance("wr_assistant", replace=True)`) —
  a second launch kills the previous one.
- Ryze assist auto-starts 100ms after launch; engine watchdog auto-restarts the
  AHK runtime every 3s if it died.
- Engines (deathwatch/autocontinue/accept) run a parent watchdog
  (`single_instance.start_parent_watchdog`, 2s interval): they exit when the
  GUI process dies, so no orphan engines linger.
- Run engines standalone: `python deathwatch.py --replace` (or autocontinue/accept).
- Logs: unhandled exceptions → `crash.log` in project root.

## Tests

```
python -m pytest tests/ -v
```

- `tests/conftest.py` adds project root to `sys.path`.
- `test_imports.py`: imports non-GUI modules (`ahk_builder`, `champions`,
  `digit_reader`, `locales`, `process_runner`) and py_compiles every `.py`
  under the tree (skipping `.saipen/` and `.git/`).
- GUI modules (`capture`, `window_ctl`, `key_blocker`, `single_instance`,
  `theme`, `accept`, `autocontinue`, `deathwatch`, `ahk_generator`) are
  compile-checked only — they need Windows/pywin32 at import time.

## Code conventions

- **UI**: vintage theme via `theme.py` (`TOKENS`, `apply_base_theme`,
  `VintageButton/Label/Entry/Notebook/Sunken`); never raw ttk styling.
  `vintage_widgets.py` adds pickers: region editor, template picker, window
  picker, image popup, capture preview.
- **Locale**: every user-facing string through `Locale.tr()` (`locales.py`);
  33 languages, chosen via native-name combobox in the bottom bar
  (`Locale.set_lang`/`toggle`), config `lang` persists any code. Tabs with
  dynamic labels implement `apply_locale()`.
- **Tabs**: all 9 tabs built at startup (`_build_all_tabs`), registered in
  `main.pyw._tab_specs`; no lazy-load guards needed.
- **Threading**: workers never touch tkinter directly — marshal via
  `root.after(0, ...)` (`_apply_worker`, `_watchdog_worker`).
- **Config**: tab `get_data()`/`get_toggles()` → `collect_config()` →
  `save_config()`; debounced auto-save via `<<AutoSave>>` event (300ms).
- **Combo syntax**: comma-separated keys, `{Space}` braces, `key:ms` per-step
  delay; q/w/e/r shift-cast unless `use_shift` false; `qwer_as_uiop` maps to
  BlueStacks keybind layout.
- **AHK**: never hand-edit `wr_runtime.ahk` (generated); the old `wr.ahk` is
  retired automatically on start. SendInput + `CoordMode Client` + per-window
  `WinActive` guards — strict BlueStacks-only input.
- **Engines**: standalone `main(replace=False)` + `load_config()` with
  FATAL+exit on bad config; tab launches with `--replace` for clean takeover.

## Audit tools (`tools/`)

Internal, dev-only scripts (each with its own `main()`):

| Script | Purpose |
|---|---|
| `ast_hunt.py` | AST audit, 15 categories: unused vars, uncalled funcs, dead code, except classification, mutable defaults, shadowing, hotspots, deep nesting, etc. |
| `deep_hunt.py` | Deeper: McCabe complexity, dependency graph, security scan, type coverage, duplicate lines, secrets scan |
| `meta_hunt.py` | Meta-level sweep (knowledge/minimap architecture etc.) |
| `exec_hunt.py` | Executable-behavior audit |
| `runtime_hunt.py` | Runtime behavior audit |
| `git_hunt.py` | Git-oriented audit |
| `record_burst.py` | Frame-burst capture of the death screen (`burst_death` output) for template work |

Run any as `python tools/<name>.py`. They are scanners/reporters — they never
modify project files.

## Docs convention

README has locale variants (`README.ee.md`, `README.ru.md`, `README.ded.md`,
`README.ja.md` noted in the header). This `docs/wiki/` tree is the detailed
documentation: architecture, config reference, tabs guide (saiwiki output).