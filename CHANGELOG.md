# Changelog








## v0.3.42 (2026-08-28)
- W2-003 audit (T-227): single_instance.start_parent_watchdog no longer reopens a bare parent PID after pinned-identity loss. If the initial OpenProcess fails, the engine fails closed (exits); if the wait on the pinned handle errors, it fails closed instead of reopening by PID. A recycled PID can no longer attach the child to an unrelated process. New test_single_instance.py regressions: pinned-wait-failure-exits (asserting no PID reopen), initial-OpenProcess-failure-exits.
## v0.3.41 (2026-08-28)
- W2-002 audit (T-226): main.pyw publishes the runtime-PvP inactive sidecar idempotently at startup (before any auto-starting DeathWatch child), at the end of stop_everything (after a proven AHK stop), and in quit_app. A stale active trigger from a prior session can no longer be consumed by DeathWatch before a current-session Apply succeeds; only a successful current-session Apply activates a trigger. Failed startup Apply never exposes a stale trigger; normal quit leaves inactive authoritative.
## v0.3.40 (2026-08-28)
- W2-001 audit (T-225): main.pyw Apply/DeathBuy/Stop is now a monotonic request stream. Every intent bumps the engine generation. A busy Apply/DeathBuy captures the latest intent as a pending request (full Apply supersedes DeathBuy, repeated requests coalesce to latest) instead of being dropped. A newer Stop bumps the generation so the older Apply/DeathBuy completion cannot kill the new runtime, and cancels any pending restart. _apply_done and _stop_engine_done drain the pending request after committing. New tests/test_main_ordering.py covers busy-retain, coalesce-to-latest, full-Apply-supersedes-DeathBuy, stop-cancels-pending, and stop-shares-_applying.
## v0.3.39 (2026-08-28)
- CORE-005 audit (T-223): deathwatch.py runtime PvP sidecar publication is now crash-safe. _remove_if_present distinguishes absent (returns False) from real deletion failure (raises OSError). _set_runtime_inactive publishes the inactive marker FIRST (reader is fail-safe even if subsequent stale-active remove fails). _write_runtime_trigger requires successful removal of the inactive marker before reporting True; a failed remove reports False without erasing the active file. On active-write failure, an authoritative inactive marker is durably published. New tests/test_runtime_trigger.py covers all 6 audit regression cases.
## v0.3.38 (2026-08-28)
- CORE-004 audit (T-222): single_instance._target_any_alive now enumerates process image names via Toolhelp CreateToolhelp32Snapshot + Process32First/Process32Next instead of opening every PID. A protected or inaccessible unrelated process can no longer poison a no-match scan into UNKNOWN, so exit_when_bs_gone fires reliably after the emulator exits. Snapshot-enumeration failure alone returns None (genuine scanner failure). Existing watchdog tri-state semantics preserved.
## v0.3.37 (2026-08-28)
- CORE-003 audit (T-221): main.pyw._reconcile_target_watchdog now takes an explicit config snapshot parameter (cfg). Cryptographic-level: callers in _apply_done pass the accepted candidate, and _build_all_tabs/import_config pass the freshly imported config, instead of silently reading the mutable self.config draft. GUI autosave and draft edits during an in-flight Apply can no longer disable or retarget the watchdog against unrelated state.
## v0.3.36 (2026-08-28)
- CORE-002 audit (T-220): main.pyw transaction journal (config.local.json.txn) is now a mandatory precondition for either half-write. _txn_write returns True/False (no longer silently swallows OSError); save_config aborts with both halves untouched when the journal cannot be published. _txn_recover now returns an explicit enum (NONE/RECOVERED/PENDING_FAILED/INVALID_JOURNAL), and load_config refuses to merge live halves when a transaction is unresolved. Rollback failure no longer clears the journal, preserving evidence for the next startup. New tests/test_core_002_txn.py covers all 9 failure modes.
## v0.3.35 (2026-08-28)
- CORE-001 audit (T-219): ahk_generator._force_kill_ahk_processes now opens each PID as a pinned PROCESS HANDLE and re-verifies ownership via _handle_ownership before the destructive call. PID-reuse window between _pid_alive() and taskkill no longer exposes foreign processes to termination; foreign/unknown cases are now no-ops, only verified-owned targets are killed through the handle, and failed escalation returns KILL_FAILED truthfully without erasing the PID file or verified cache. New tests/test_ahk_generator.py covers owned/foreign/unknown/openprocess-denied/wait-timeout cases.


## v0.3.34 (2026-08-19)
- CORE audit (17 tickets): degraded startup can no longer launch without a last-applied config; failed process observation never becomes verified absence; destructive process identity is bound to the same instance throughout kill; failed termination keeps the child tracked; failed config recovery leaves no durable candidate half; T-204 physical input cannot hit a non-game target and uses last-applied trigger truth; canonical config validation gates all AHK side effects; legacy migration preserves data; corrupt OCR resources never enter live state; unsafe engine configs cannot autostart; process watchdogs preserve instance/UNKNOWN truth; surrender action is explicit; hide/quit/forced-shutdown and persistence semantics are distinct; defaults have one behavioral source; audit tools remain truthful.
- Second wave (12 tickets): replacement cannot kill last-good engine over bad candidate; monitor OFF failure never lies about runtime; independent engine Apply cannot activate unrelated AHK draft; main import preserves independent engine edits/processes; DeathTab no longer overwrites externally hot-reloaded resource fields; Accept/Surrender fail closed on zero usable templates; Active Hotkeys shows last-applied runtime only; cross-drive template selection cannot crash; export cannot truncate existing destination; same-second backups cannot collide; valid multi-monitor geometry round-trips; stale window-picker workers cannot overwrite newer UI state.
- Performance (7 tickets): ProcessRunner line output coalesced to bounded deque (no 11MiB burst, one UI set per tick); AHK preflight timer injected before first label (600ms self-exit vs 1.5s timeout); cached launch handle for cheap liveness; AutoContinue one full capture per background poll; target watchdog early-exit positive scan; 1ms timer resolution scoped to DeathWatch only; identical Apply performs no runtime churn via script hash cache.
- Tests: suite 633 -> 653 PASS, pyflakes 0.

## v0.3.33 (2026-08-19)
- Deathwatch resurrect click now lands INSIDE the game: the phase-3 action waits until the game is really the foreground window (plus a settle pause) before firing, and the resurrect mid-click is posted straight into the game window instead of crashing on a never-implemented helper - a context menu of another program can no longer pop over the game (T-202).
- Spam cursor guard is now a three-way choice (toggles.cursor_outside_mode): pause (default) skips clicks while the cursor is outside the game but keeps the mechanism armed - it resumes the moment the cursor is back; stop kills the running spam entirely on cursor leave; no-guard disables the check. The movement re-hold after focus return is deferred until the cursor is over the game, so the restore right-click can never open another window's context menu (T-203).
- New "Cursor outside game" combobox on the Main tab, config whitelist validation, 34 locale bundles.
- Tests: suite 614 -> 633 PASS, pyflakes 0.

## v0.3.32 (2026-08-12)
- Safety audit pass 6, 12 tickets (T-181..T-191, T-195). AHK ownership is now EXACT-TOKEN: the identity scan fetches pid+command-line as JSON and requires the first script argument to equal wr_runtime.ahk exactly (no substring regex); every kill opens a process HANDLE and re-verifies that same instance as an AutoHotkey binary before terminating (PID-reuse TOCTOU closed); stop_ahk returns a result contract - on an UNKNOWN identity scan it retains the PID file and cache instead of erasing ownership; verified cache data keeps its own clock (failed scans never extend its TTL, is_running returns UNKNOWN instead of guessing) (T-181, T-182, T-183, T-184).
- Apply determinism: the Apply candidate is deep-copied and frozen on the main thread - editor/autosave mutations mid-generation can no longer change what is generated or recorded as applied; the watchdog freezes its restart candidate the same way (T-185). save_config(False) now means NO durable half was committed (a blocked local half refuses the whole save instead of reporting partial success); failed recovery rolls back the previous local as exact bytes (never re-parsed); recovery writes never overwrite a good .bak with a rejected source (T-186, T-187, T-188).
- AHK replacement is transactional after the commit point: the previous script is snapshotted and restored (with a best-effort relaunch) if the candidate fails to launch, and an UNKNOWN previous-owner state aborts replacement instead of doubling the runtime (T-189, T-190).
- Hot reload can no longer kill a healthy engine: a semantically-invalid revision is rejected whole and the last-good config keeps running (startup stays FATAL); the same policy now covers the deathwatch resources and JSON in one transaction (T-191).
- Tests: suite 593 -> 614 PASS, pyflakes 0.

## v0.3.31 (2026-08-11)
- Safety audit pass 4, 8 tickets (T-173..T-180). ProcessRunner: a stream failure while the child is still alive deliberately terminates it instead of marking Stopped and losing ownership - a live child is never left untracked (T-173).
- Config/codegen: champions booleans require exact bool (qwer_as_uiop="false" can never enable the QWER->UIOP remap), a canonical trigger grammar rejects malformed hotkeys before generation, config strings interpolated into AHK (target_exe, window_title, template paths) are validated for AHK-unsafe characters, and unmapped Unicode combo keys are rejected (native probe: AHK would send them as literal text into the game) (T-174, T-175, T-176, T-180).
- Runtime-state determinism: the watchdog now resurrects the LAST-APPLIED config, not the mutable editor draft - Apply is the explicit activation gate, no crash-dependent behavior; the deathwatch resurrect mid-click reads the main config through the shared validator with an in-client-bounds check (UNKNOWN => no click) (T-177, T-178).
- default_config deep-copies its nested defaults (T-179).
- Tests: suite 543 -> 593 PASS, pyflakes 0.

## v0.3.30 (2026-08-11)
- Safety audit pass 3, 10 tickets (T-163..T-172). Generated AHK no longer closes other AHK processes by filename wildcard (^wr.*\.ahk) - ownership and replacement are python-side, PID/identity-verified only (T-163).
- AFK farm: never fabricates map coordinates (no invented Mid fallback; enabled-with-zero-positions is disabled and reported), positions no longer depend on the minimap hotkey trigger, and the death detector fails CLOSED - ImageSearch ErrorLevel 2 (search could not be conducted) pauses AFK instead of running the alive path; the deathwatch config is consumed through the canonical validator with a template-resource check (T-164, T-165, T-166).
- Autobuy now loads deathwatch_config.json through the canonical engine validator and the canonical quickbuy parser - an enabled autobuy with invalid/corrupt config is a rejected candidate, never a silent no-op (T-167).
- Validators: afkfarm covers move_duration/combo_interval/follow_cursor (string "false" can never become bool True); unknown mode ("general" or a configured champion) is rejected (T-168, T-172).
- Persistence: config.local.json has its own write guard (an unsafe local file is never overwritten by a healthy primary save); a failed two-file save rolls back the local half so no durable hybrid state survives (T-169, T-170).
- ProcessRunner: a dead child is cleared before a replacement spawn - a failed spawn leaves proc=None (T-171).
- Tests: suite 449 -> 543 PASS, pyflakes 0.

## v0.3.29 (2026-08-11)
- Safety audit pass 2, 11 tickets (T-150..T-162). Monitor OFF fixed: save_monitor_state now returns the persistence result, so the checkbox no longer bounces back to ON after a successful disable (T-150).
- Engine config contracts: autocontinue buttons now require name/template/region/threshold (runtime indexes them directly) and all pixel-coordinate regions must be integer pixels - bool/float coordinates are rejected (T-151). The GUI reads engine configs through the engine's own validator: nested garbage parses as display-canonical and can never be written back over (T-152).
- Deathwatch: region reads are occlusion-safe (foreign screen pixels can never trigger automation), only real window/capture errors are treated as "lost window", and hot reload commits config + templates atomically or not at all (T-153, T-154, T-155).
- Recovery integrity: a failed import keeps the write guard armed, backup aborts instead of copying a corrupt source, and a failed save never leaves the primary config ahead of the failure (T-156, T-157, T-161).
- Identity: single-instance kill protection now requires the exact absolute script path - a same-named script in another directory is never killed (T-158). grab_region rejects zero/negative sizes before any GDI allocation (T-162). Canonical defaults are deep-copied (T-159).
- Tests: suite 449 -> 500 PASS, pyflakes 0.

## v0.3.28 (2026-08-11)
- Safety audit pass, 15 tickets (T-135..T-149). Config: fail-closed read/write with a write-guard that blocks saving over a corrupt/unreadable config, validated `.bak` restore, and deep semantic validation of combos/champions/minimap/afkfarm/toggles (T-135, T-136). Engine-tab JSON I/O: guarded read-modify-write that never overwrites an unsafe source, complete canonical defaults on first run, atomic saves with `.bak`, one canonical defaults source per engine (T-137, T-141).
- Engines: autocontinue never blind-clicks on a missing template and refuses to start with zero usable targets; per-engine REQUIRED config contracts (runtime-indexed keys); one canonical quickbuy-key parser shared by validator and runtime; save failure aborts apply/monitor start; only real window/capture errors are treated as "lost window", other failures are fatal instead of looping (T-138, T-139, T-140, T-142, T-149-B).
- Windows/integration: watchdog gives the GUI a bounded cleanup window instead of killing it mid-shutdown; single-instance identity is exact-token, not substring; file-drop parsing survives spaces/braces/URIs; region capture is occlusion-safe (PrintWindow fallback); PrintWindow GDI/DC handles can no longer leak (T-143, T-144, T-145, T-146, T-147).
- Hygiene: dead `VERSION` constant removed, CHANGELOG is the single version source; tray Quit marshals to the Tk thread (T-148, T-149-F).
- Tests: suite 341 -> 449 PASS, pyflakes 0.

## v0.3.27 (2026-08-10)
- Champions: roster sync (T-134). Verified the roster against the live official champion list — all 140 champions current, only Cho'Gath was missing; added with a placeholder combo.
- Tests: suite 341/341 PASS, pyflakes 0.

## v0.3.26 (2026-08-10)
- Types: type-hint baseline for core modules (T-132). Public functions in `config_store.py`, `engine_config.py`, `capture.py` and `champions.py` are annotated (typed_pct 0 -> 2% project-wide).
- Tests: suite 341/341 PASS, pyflakes 0.

## v0.3.25 (2026-08-10)
- Logging: engines and core infra now use Python logging (T-131). `engine_config.setup_logging()` configures a root logger at every entry point (GUI, deathwatch, accept, surrender, autocontinue); the silent catch-all paths in `single_instance.py`, `capture.py`, `key_blocker.py` and `process_runner.py` log at debug/warning instead of swallowing. meta_hunt health score 58 -> 68 (was flagging "no logging module imported anywhere").
- Tests: suite 341/341 PASS, pyflakes 0.

## v0.3.24 (2026-08-10)
- Tools: exec_hunt report drift fixed (T-130, from the T-129 MARKHUNT audit). The config validator hardcoded pre-migration schemas (`lang`/`window`/`hotkeys`/`emulator` for config.json, `enabled`/`interval` for the engine configs), so every run reported 43 false MISSING/UNKNOWN keys. It now delegates config.json structure to `config_store.validate_config` (the runtime's own source of truth) and validates deathwatch/autocontinue against their real key sets — 0 false issues. Module-safety checks now recognise the `if __name__ == "__main__":` guard, skip `.saipen/` agent scratch, and the Windows path normalization makes the side-effect blacklist actually match (it never did on backslash paths). Cat7 noise: 271 -> 1; Cat1 false import FAILs: 81 -> 0.
- Tests: suite 341/341 PASS, pyflakes 0.

## v0.3.23 (2026-08-09)
- Tools: meta_hunt health report now derives from the live tree (T-128). The old recommendations + health score were a static literal snapshot ("323 funcs", "config.json orphan lang,window" — false: lang consumed by config_store.py, window not even a key); now computed: type-hint coverage, max cyclomatic complexity, bare-pass except handlers, logging import presence, config.json orphan keys, live builtin-shadowing/dead-import counts, real AHK scan. Score was constant 36, now computed 58.
- Tests: suite 341/341 PASS, pyflakes 0.

## v0.3.22 (2026-08-09)
- Perf: low-lag polling at fast intervals (T-127). Accept/surrender used to re-render the whole window (PrintWindow) every tick; an optional per-template `region` in the config now switches them to a cheap screen-region BitBlt (`grab_region`) of just the button area — ~100x less work per poll, so a <32ms interval stops lagging the emulator. No region set = old full-window behavior (backward compatible).
- Perf: engines and the GUI now raise the Windows timer resolution (`timeBeginPeriod(1)`) for their lifetime, so short poll sleeps aren't quantized to the ~15.6ms default quantum and a configured 32ms interval actually polls at 32ms.
- Tests: suite 338/338 PASS, pyflakes 0.

## v0.3.21 (2026-08-09)
- Fix: `tools/ast_hunt.py` crashed on RU-locale Windows (T-126) — the mergeable-imports message carried a `→` (U+2192) that the cp1251 console cannot encode, so the report died mid-run with UnicodeEncodeError. Replaced with ASCII `->`; the tool now completes under `PYTHONIOENCODING=cp1251`. Same class as the v0.3.19 git_hunt fix. Reproduction + regression in saitest scenario011.
- Tests: suite 331/331 PASS, pyflakes 0, ast_hunt rc=568 under cp1251 (no crash, SUMMARY reached).

## v0.3.20 (2026-08-08)
- Fix: casting abilities manually (q/w/e/r/d/f/c) no longer releases the LMB move-hold — the champion keeps running while you cast, checkbox on or off. The 1-7/G release stack (gated on `release_toggle_on_keys`) and the untoggle keys are the only remaining releasers.
- Change: PVP combo release (toggle-off, hold-up, RMB-hold end) now latches the move-hold on when its MoveRefs is the last one — the champion keeps walking until you click LMB again. B recall-stop, stop key and untoggle keys still stop it; wave/jungle combos keep the old stop-on-release.
- Tests: suite 331/331 PASS, pyflakes 0, AHK preflight OK.

## v0.3.19 (2026-08-08)
- Fix: `tools/git_hunt.py` crashed on every run (T-116) — git log dates are offset-aware but `datetime.now()` is naive, so comparisons raised TypeError. New `_naive_dt()` strips the timezone offset; the tool now runs clean.
- i18n: locale bundles overhauled (T-117/118/120/121) — `untoggle_keys_lbl` + `tt_untoggle_keys_lbl` added to every bundle (ru/et/ded previously fell back to English or showed the raw key); `toggle_release_on_keys` reworded to the post-v0.3.16 B-recall-stop / untoggle-a,v behavior; 29 owned bundles got real translations instead of EN placeholders; 15 dead keys removed from all 33 bundles; inline `locales.py` en/ru dicts synced to match (they are the runtime + parity source).
- Chore: ToolTip on the untoggle-keys entry localized via `tt_untoggle_keys_lbl` (T-118), replacing the hardcoded English string from T-101.
- Docs: CHANGELOG v0.3.16 section restored (T-119) — the ship bump had renamed it to v0.3.17; v0.3.17 now records its own 29-bundle locale sync.
- Chore: duplicate `_check` Checkbutton factory deduped into `theme.make_check()` (T-123) — main_tab + combo_tab import it.
- Chore: tools/*.py helper triplication deduped into `tools/_common.py` (T-122) — get_py_files / short_path / parse_file defined once, ~12 copies removed; all 6 scanners still run.
- Chore: dead `mss` dependency dropped from requirements.txt (T-124) — screen capture uses win32ui.
- Tests: suite 328/328 PASS, pyflakes 0, digest 2/2.

## v0.3.18 (2026-08-08)
- Chore: dead `bevelLight` theme token removed (T-115) — defined in theme.py but referenced nowhere; the bevel pair is `borderHighlight`/`borderDark`.
- Chore: sc crew circuit — sense (hunt) clean, saitest all reviewed (no new reproductions), EE + QQ packages force-fresh and collected (zero-diff / payload-none).
- Tests: suite 328/328 PASS, pyflakes 0, digest 2/2.

## v0.3.17 (2026-08-07)
- i18n: 29 saitranslate-owned locale bundles synced for the input-settings batch keys (EE/QQ pipelines) — `untoggle_keys_lbl` added, `toggle_release_on_keys` reworded to the new B recall-stop / untoggle a,v behavior in all 29 owned bundles.

## v0.3.16 (2026-08-07)
- Fix: B (recall) now fully stops a running PVP combo + the move-hold so the recall lands — combo flags and step counters are cleared, the move-hold is released, and the key still passes through to the game. Previously the combo kept spamming through the recall.
- Fix: Space (attack) no longer releases the move-hold or stops PVP — attack while moving keeps the PVP hold and movement going. Space is a pass-through + space-spam trigger only.
- Change: the keys that release the LMB move-hold are now configurable via `untoggle_keys` (comma-separated, default `a,v`); `b` is reserved for the recall-stop and is ignored in the field.
- Change: the 1-7/G release stack only acts while `release_toggle_on_keys` is on; the configurable untoggle keys always release.
- Fix: bottom button bar clipped at the default window size — default window 750x550 → 920x550 (geometry + clamp), status label capped at 64 chars so long warnings cannot push the buttons out.
- Docs: `config-reference.md` gains `mouse_toggle_hold`/`release_toggle_on_keys`/`untoggle_keys` rows; `tabs-guide.md` documents B recall-stop, untoggle keys, Space-is-attack and the 920 window; EN locale gains `untoggle_keys_lbl`.
- Tests: suite 320 → 328.

## v0.3.15 (2026-08-07)
- Fix: AHK replacement is now transactional — the candidate script is rendered and validated in memory (parse `ValueError`, same-context hotkey duplicates = fatal, best-effort real-AHK syntax preflight on a temp copy) before the live script file is touched, the old runtime is stopped, or a launch happens. A rejected candidate never kills or clobbers the last-good runtime; the GUI's status dot reflects the actual runtime state instead of the apply result.
- Fix: engine watchdog no longer auto-restarts in a loop — the PID scan's PowerShell query had a backtick before `$_.CommandLine` (treated as a command name → scan always returned an empty set) and a double-backslash `-like` pattern that never matched a real command line. Both replaced with plain member access + `re.escape` regex `-match`. Live-verified.
- Fix: AHK process identity verified before kill/report — the PID file is a hint only; a tracked PID is killed only when a command-line scan proves it runs `wr_runtime.ahk` (stale reused PIDs are never terminated). Same for `single_instance` (engine script in the command line required before terminating a previous holder).
- Fix: throttle is not "no process" — a skipped PID scan reuses the last verified result; explicit stop always force-scans.
- Fix: `ProcessRunner` isolates process generations — the pump captures the child locally, tags every line/done event with its generation, and `poll_log` drops stale events; a spawn failure leaves a coherent stopped/error state.
- Fix: config validation before merge — `config.json` sections are shape-checked (toggles dict / combos list / champions dict / minimap dict / afkfarm dict) and malformed-but-valid JSON is rejected before any migration or merge; `config.local.json` is validated and bad local state ignored. Config import validates before overwriting the live file.
- Fix: engine configs fully semantically validated (finite numerics, bool-not-numeric, thresholds 0..1, region extents, quickbuy key/presses, blocked keys, bool/str fields); hot reload uses the same validator; deathwatch template reloads are transactional; `run_poller`/deathwatch load before probing mtime.
- Fix: click at (0,0) — template-match sentinels use explicit `is None`; a threshold-passing match at the top-left corner clicks.
- Fix: surrender tab lifecycle parity with its siblings (`_tick` polls the runner, `save()` guards invalid input, apply saves first); key_blocker recovers after a dead pump thread; scaled-template build clamps dimensions ≥ 1 (1×1 template + 0.8 scale no longer produces a zero-size resize).
- Tests: suite 225 → 320 (+95).

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
