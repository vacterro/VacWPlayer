# Changelog

## v0.3.14 (2026-08-07)
- Refactor: `tabs/champ_tab.py` renamed to `tabs/bind_button.py` — the file held only `BindButton` since the legacy `ChampTab` class was removed; the old name misled. 4 importers updated (afkfarm/champion/combo/minimap tabs); `tabs.bind_button` added to the import smoke test.

## v0.3.13 (2026-08-07)
- Fix: hotkey conflict scan canonicalizes modifier order — `_canon_hotkey` now normalizes modifiers via `_canon_mods` (sorted tokens; `<^`/`>^` L/R variants kept distinct), so `^!x` vs `!^x` (one chord to AutoHotkey, exit 2 "Duplicate hotkey") is caught instead of silently passing. Generated script with that collision previously refused to start at all.
- Tests: 3 new conflict-scan regression tests (modifier-order twins, triple variants, L/R distinctness). Suite 222 → 225.

## v0.3.12 (2026-08-07)
- Fix: engine configs type-checked on load — `engine_config.validate_engine_config` rejects wrong-typed values (`window_title: 12345`, `poll_interval_sec: "abc"`, `buttons: "notalist"`) with the same FATAL/`SystemExit(1)` path as corrupt JSON, instead of loading silently and crashing mid-loop (`time.sleep("abc")` TypeError, `find_window(12345)`). Wired into `poller_engine.load_config` (accept/surrender/autocontinue) and `deathwatch.load_config`; deathwatch gained module-level `CONFIG_PATH` for uniformity.
- Tests: 14 new wrong-type regression tests (all 4 engines × window_title/poll_interval/templates + valid-types pass + CONFIG_PATH). Suite 206 → 222.

## v0.3.11 (2026-08-07)
- Fix: malformed combo keys rejected at generation — `parse_steps` now validates every step against an AHK send-name whitelist (letters/digits incl. Cyrillic, F1-F24, `{named}` keys) and raises a clear `ValueError` on junk like `q:`, `q:-100`, `ц:{Space}:50`. Previously these rendered as `{q:}`/`{q:-100}` send-names that AutoHotkey silently ignored (exit 0) — a dead combo with no error. Note: modifier-prefixed step keys (`!q`) were undocumented and are now rejected.
- Tests: 11 new `parse_steps` regression tests (valid whitelist, 6 junk cases, comma-only, `generate_script` rejection). Suite 195 → 206.

## v0.3.10 (2026-08-07)
- Tests: README mirror digest regression test (`tests/test_readme_digests.py`) — recomputes the normalized sha256 of `README.md` (CRLF→LF, `N.N.N`→`VERSION`) and asserts all 4 locale mirrors carry a matching `source-digest` marker; missing and stale markers fail distinctly. Guards the drift class fixed in v0.3.8 (mirrors silently stale, markers re-stamped to a value that no longer matched the source).

## v0.3.9 (2026-08-07)
- CI: GitHub Actions workflow (`.github/workflows/ci.yml`) — pytest + pyflakes on push/PR (windows-latest, Python 3.11, pip cache, concurrency cancel). Repo had zero CI despite 193 tests and 6 releases; regressions were only caught locally.

## v0.3.8 (2026-08-07)
- Docs: root README mirrors (ee/ja/ded) re-synced to current README.md content — Disclaimer sections added, AFK Farm / Buy-Accept-Surrender / Minimap feature bullets, idle-prevention terms; all 4 source-digest markers re-stamped to b1c6e5b71595a204 (SAIT-006 collect).

## v0.3.7 (2026-08-07)
- Fix: silent `except: pass` removed from 4 engine-tab `stop_all()` methods — monitor-toggle reset failures now log to stderr (HUNT cat-4). Remaining silent-except sites audited: 24 benign-by-design (Tk teardown idiom, probes, cleanup).

## v0.3.6 (2026-08-07)
- Config: volatile runtime state (window geometry, per-champion `enabled_*`/`toggle_*`) split into gitignored `config.local.json` on save, overlaid on load — `config.json` stays commitable, no per-user dirty diffs from a GUI run. Legacy volatile keys migrate on first save.

## v0.3.5 (2026-08-07)
- Tests: `poller_engine.run_poller` behavioral coverage (7 tests) — acquire/scan/click sleep pattern, grab-failure retry keeps hwnd, config reload rebuilds targets, window-title change re-acquires, acquire-failure retry, lost-window reset. Suite 178 → 185.

## v0.3.4 (2026-08-07)
- Fix: RMB remap/PVP-hold now gated on cursor-inside-window (`MouseIsOver`) like LMB — cursor off the game (desktop/taskbar/second monitor) while PVP runs no longer produces left-clicks on the desktop. Pass-through preserves the real right-click.

## v0.3.3 (2026-08-07)
- Refactor: extracted shared template-poller engine (`poller_engine.py`) — accept/surrender/autocontinue now share the poll loop (single-instance, parent watchdog, config mtime reload, window acquisition, template-match click). Net -183 lines, behavior preserved, +1 structural test (176 suite).
- Docs: architecture.md notes `poller_engine`.

## v0.3.2 (2026-08-07)
- Docs: fixed doc-drift cluster from MARKHUNT — README + 4 locale mirrors (ded/ee/ja/ru) back to v0.3.1, per-champion tabs (Ryze/Xin removed), 5 configs, missing Buy/Accept/Surrender/Minimap features; docs/wiki: 10 tabs (no lazy load), 33-language combobox, mutex-based single-instance, surrender_config.json reference, Surrender tab section. saiwiki kitchen docs re-synced; CHANGELOG + saiwiki OUTBOX encoding repaired.

## v0.3.1 (2026-08-07)
- Fix: `_find_our_pids` swallow-all `except Exception: pass` removed — probe failures now log to stderr; timeout retries once then gives up. Watchdog no longer goes blind on a failed PowerShell probe.
- Tests: PID-scan paths (probe parse/empty, throttle, timeout-retry, double-timeout, other-exception) — 8 tests. Suite 167 → 175.

## v0.3.0 (2026-08-07)
- Config resilience: atomic writes with `.bak` backup before every save; corrupt config.json restored from `.bak` on load (messagebox notifies user); light structural validation with stderr warnings; corrupt-without-backup falls back to defaults with a warning instead of silent data loss.
- Tests: `config_store` unit coverage (read/atomic-write/restore/validate) + `load_config` corrupt/missing paths — 21 tests. Suite 146 → 167.

## v0.2.9 (2026-08-07)
- Tests: MinimapTab dynamic-slot logic (merge/order/add/remove/get_data) — 10 tests via Tk-free stub. Feature itself shipped in initial release; this closes the coverage gap.
- Suite 136 → 146.

## v0.2.8 (2026-08-07)
- Tests: ProcessRunner done-event path (child death -> "Stopped"/check_var False, stale-generation guard, line pump) — 4 tests.
- Refactor: duplicated config mtime-reload check in all 4 engines extracted to shared `engine_config.mtime_changed` (accept/surrender/autocontinue/deathwatch).
- Tests: `engine_config.mtime_changed` changed/unchanged/missing-file — 3 tests.
- Suite 129 → 136.

## v0.2.7 (2026-08-07)
- Tests: ahk_builder E-141 carry-guard direct coverage (GuardCarry, FocusWatch stale-carry sweep, guard variant emission, _guard_variant/_guarded_triggers/_carry_set/_base_key).
- 40 new tests, suite 89 → 129.

## v0.2.6 (2026-08-07)
- Tests: window_ctl unit coverage 22% → 100% (click/press/release, foreground fallback, key_vk, dpi).
- Tests: key_blocker coverage 42% → 78% (VK map, hook proc block/pass/release-window, block_pedals, start/stop lifecycle).
- 40 new tests, suite 46 → 89.

## v0.2.5 (2026-08-07)
- Rebrand: WildRiftAssistant → VacWPlayer across all 46 files (app title, window, tray, error dialogs, READMEs, docs, launchers, locale bundles).
- Terminology: Anti-AFK → Idle Prevention, AFK Farm → Rotating Farm, AFK ms → Idle ms, Enable AFK Farm → Enable Rotating Farm (33 locale JSONs + locales.py).
- README: Fixed outdated Ryze/Xin Zhao tab references → Champions/Rotating Farm tabs. Added ToS disclaimer (EN + RU).
- Docs: Architecture tab count 9→10 (added surrender engine). BlueStacks references generalized in capture.py, deathwatch.py, window_ctl.py.
- Champions: Source URL fixed (wildriftcore.com → wildrift.leagueoflegends.com).

## v0.2.4 (2026-08-07)
- Hunt+fix wave: 5 defect tickets from 6-category sweep.
  - P0: `_write_pid` OSError crashes app at startup (disk full/permission denied). Added error handling.
  - HIGH: Surrender tab missing `stop_all()`, toggle_monitor didn't save state, quit/rebuild/stop skipped surrender engine. Fixed integration symmetry with death/auto/accept tabs.
  - P1: `toggle_mouse_lock` return value discarded at both call sites. Logs warning on failure.
  - P1: `taskkill` returncode unchecked in `_stop_pids`. Logs warning on non-zero.
  - P1: `reset_defaults` bare `except Exception: pass` overwrote corrupt config silently. Split into FileNotFoundError (silent first-run) + JSONDecodeError/OSError (messagebox warning).

## v0.2.3 (2026-08-07)
- digit_reader unit tests: white-text mask (saturation gate), column segmentation (merge/noise), glyph matching, read_number (synthetic digits, min-score, non-numeric). Coverage 16% -> 57%.

## v0.2.2 (2026-08-07)
- AHK hotkey conflict detection: post-generation scan of the rendered script flags duplicate hotkeys (including collisions with fixed generated hotkeys like the ~*b release handler, ^g anti-AFK, and the ExitApp chord) that AutoHotkey would silently resolve last-wins.

## v0.2.1 (2026-08-07)
- Engine unit tests: config-load (valid/missing/corrupt) for all 4 engines, ProcessRunner start/stop/restart lifecycle, hwnd acquisition, region grouping, template scaling.

## v0.2.0 (2026-08-05)

### Features
- Surrender monitor engine (surrender.py) + Surrender tab: watches for vote dialogs via PrintWindow, auto-accepts or auto-declines per mode, scale-adaptive templates.
- BlueStacks-exit watchdog: assistant auto-closes when the emulator process is gone (`exit_when_bs_gone` toggle, default on).
- Layout-independent hotkeys: triggers and combo keys emitted as scan codes (`sc010`), Cyrillic-bound keys map to their physical QWERTY key.
- Multi-bind combo triggers (comma-separated, e.g. `F13,F16`) sharing one combo; mouse-button binds (MButton, XButton1/2).
- Toggle-mode combos (press to start, press again to stop) for champion slots.
- RMB-hold PVP: holding right button 0.3s+ drives the PVP combo; short RMB stays a tap-attack.
- Keep-movement-through-death: LMB toggle-hold re-engages after respawn/focus return.
- Release-move-toggle-on-keys: action keys (items, vision, abilities) cancel move-hold when enabled; recall always does.
- Auto-continue Reset now restores the original button set (deep copy).
- Delete-combo confirmation dialog.

### Fixes
- MasterSpammer ticks run atomically (Critical) — manual casts no longer get eaten by combo steps.
- Auto-accept/auto-surrender template matching picks best score across scaled templates.

## v0.0.7 (2026-08-01)
- Tooltip localization, movement controls, guard/carry rework, dead code sweep.
