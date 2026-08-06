# Changelog

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
