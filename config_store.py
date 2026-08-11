"""Config load/save with corruption guard.

config.json is user state: a corrupt file silently falling back to an empty
dict has historically overwritten every setting on the next save. This module
gives the app atomic writes with a .bak kept before every overwrite, plus a
restore path so a bad file is recovered from the last good backup instead of
dropping to defaults.
"""

import json
import math
import os
import shutil

BAK_SUFFIX = ".bak"

_SLOT_SUFFIXES = ("wave", "jungle", "pvp")


def _is_finite_number(v):
    """Finite int/float, never bool (bool is int in Python - T-082 rule)."""
    return isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def read_raw(path: str) -> tuple[object, str | None]:
    """Return (data, error). error is None, 'missing', 'corrupt', or 'io_error'.

    FileNotFoundError is 'missing' (normal first run); JSON decode failures
    are 'corrupt'; every other OSError - permission, share violation, I/O -
    is 'io_error'. The three are never collapsed: an unreadable file must not
    look like a first run, or the next save would overwrite it with defaults.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "io_error"
    except ValueError:
        return None, "corrupt"


def atomic_write(path: str, data: dict) -> None:
    """Write `data` as JSON to `path`, keeping the previous content as .bak.

    Writes to a temp file in the same directory, then replaces the target so
    a crash mid-write leaves either the old file or the new one, never a
    truncated mix. Before the replace the current file (if any) is copied to
    path + .bak, so the last good config survives even a bad write.
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
        f.write("\n")
    if os.path.exists(path):
        shutil.copy2(path, path + BAK_SUFFIX)
    os.replace(tmp, path)


def restore_backup(path: str) -> bool:
    """Copy path + .bak over path. Returns True on success, False otherwise.

    Callers MUST read and validate the .bak (read_raw + validate_config)
    BEFORE calling this - an unvalidated backup must never become the live
    config (T-135).
    """
    bak = path + BAK_SUFFIX
    try:
        shutil.copy2(bak, path)
    except (OSError, shutil.SameFileError):
        return False
    return True


def _check_toggles(problems, toggles):
    """Every KNOWN toggle must carry the type its UI/runtime variable assumes.
    Unknown keys are left alone: they may be forward-compatible flags no
    current consumer reads (T-136)."""
    from tabs.main_tab import TOGGLE_DEFAULTS  # lazy: keeps CLI imports light
    for key, default in TOGGLE_DEFAULTS.items():
        if key not in toggles:
            continue
        v = toggles[key]
        if isinstance(default, bool):
            if not isinstance(v, bool):
                problems.append("'toggles.%s' must be a boolean, got %r" % (key, v))
        elif isinstance(default, str):
            if not isinstance(v, str):
                problems.append("'toggles.%s' must be a string, got %r" % (key, v))
        else:  # int
            if not _is_int(v):
                problems.append("'toggles.%s' must be an integer, got %r" % (key, v))


def _check_combos(problems, combos):
    """ComboTab._refresh_tree indexes c['trigger'], c['keys'] and c['interval']
    directly, and _show_hotkeys formats interval with %d - every combo element
    must be an object carrying exactly those fields with safe types (T-136)."""
    for i, c in enumerate(combos):
        if not isinstance(c, dict):
            problems.append("'combos[%d]' must be an object, got %r" % (i, c))
            continue
        for f in ("trigger", "keys"):
            if f not in c:
                problems.append("'combos[%d]' is missing required field %r" % (i, f))
            elif not isinstance(c[f], str):
                problems.append("'combos[%d].%s' must be a string, got %r"
                                % (i, f, c[f]))
        if "interval" not in c:
            problems.append("'combos[%d]' is missing required field 'interval'" % i)
        elif not _is_int(c["interval"]):
            problems.append("'combos[%d].interval' must be an integer, got %r"
                            % (i, c["interval"]))
        for f in ("shift", "move_when_pressed"):
            if f in c and not isinstance(c[f], bool):
                problems.append("'combos[%d].%s' must be a boolean, got %r"
                                % (i, f, c[f]))


def _check_champions(problems, champs):
    """Every champion entry is dereferenced as an object (tab form, hotkey
    display, AHK builder) - non-object entries and hostile field types must be
    rejected before any consumer sees them (T-136)."""
    for slug, entry in champs.items():
        if not isinstance(entry, dict):
            problems.append("'champions.%s' must be an object, got %r" % (slug, entry))
            continue
        if "display_name" in entry and not isinstance(entry["display_name"], str):
            problems.append("'champions.%s.display_name' must be a string, got %r"
                            % (slug, entry["display_name"]))
        for slot in _SLOT_SUFFIXES:
            for f in ("trigger_" + slot, "keys_" + slot):
                if f in entry and not isinstance(entry[f], str):
                    problems.append("'champions.%s.%s' must be a string, got %r"
                                    % (slug, f, entry[f]))
            for f in ("enabled_" + slot, "toggle_" + slot,
                      "move_when_pressed_" + slot):
                if f in entry and not isinstance(entry[f], bool):
                    problems.append("'champions.%s.%s' must be a boolean, got %r"
                                    % (slug, f, entry[f]))
        if "interval" in entry and not _is_finite_number(entry["interval"]):
            problems.append("'champions.%s.interval' must be a finite number, got %r"
                            % (slug, entry["interval"]))
        if "use_shift" in entry and not isinstance(entry["use_shift"], bool):
            problems.append("'champions.%s.use_shift' must be a boolean, got %r"
                            % (slug, entry["use_shift"]))


def _check_minimap(problems, minimap):
    """Slots are consumed as objects (MinimapTab, _show_hotkeys' %d) - non-
    object entries and non-numeric coordinates crash a consumer (T-136)."""
    for key, entry in minimap.items():
        if key == "_order":
            if not isinstance(entry, list) or not all(
                    isinstance(x, str) for x in entry):
                problems.append("'minimap._order' must be a list of strings, got %r"
                                % entry)
            continue
        if not isinstance(entry, dict):
            problems.append("'minimap.%s' must be an object, got %r" % (key, entry))
            continue
        if "trigger" in entry and not isinstance(entry["trigger"], str):
            problems.append("'minimap.%s.trigger' must be a string, got %r"
                            % (key, entry["trigger"]))
        for f in ("x", "y"):
            if f in entry and not _is_int(entry[f]):
                problems.append("'minimap.%s.%s' must be an integer, got %r"
                                % (key, f, entry[f]))


def _check_afkfarm(problems, afk):
    """AFK farm fields feed booleans/strings/AHK generation directly (T-136);
    slots are dicts of {enabled, move_when_pressed} or legacy list of names."""
    if "enabled" in afk and not isinstance(afk["enabled"], bool):
        problems.append("'afkfarm.enabled' must be a boolean, got %r" % afk["enabled"])
    for f in ("toggle_key", "combo_keys"):
        if f in afk and not isinstance(afk[f], str):
            problems.append("'afkfarm.%s' must be a string, got %r" % (f, afk[f]))
    slots = afk.get("slots")
    if slots is not None:
        if isinstance(slots, list):
            for s in slots:
                if not isinstance(s, str):
                    problems.append("'afkfarm.slots' item %r must be a string" % s)
        elif isinstance(slots, dict):
            for k, entry in slots.items():
                if not isinstance(entry, dict):
                    problems.append("'afkfarm.slots.%s' must be an object, got %r"
                                    % (k, entry))
                    continue
                for f in ("enabled", "move_when_pressed"):
                    if f in entry and not isinstance(entry[f], bool):
                        problems.append(
                            "'afkfarm.slots.%s.%s' must be a boolean, got %r"
                            % (k, f, entry[f]))
        else:
            problems.append("'afkfarm.slots' must be an object or list, got %r"
                            % slots)


def _check_window(problems, window):
    if not isinstance(window, dict):
        problems.append("'window' is not an object")
    else:
        if "active_tab" in window and not _is_int(window["active_tab"]):
            problems.append("'window.active_tab' is not an int")
        if "position" in window and not isinstance(window["position"], str):
            problems.append("'window.position' is not a string")


def validate_config(data: dict) -> list[str]:
    """Total structural check. Returns list of problem strings ([] = fine).

    Never raises: malformed-but-valid JSON must be rejected or ignored, never
    crash startup (T-086). Verifies the exact top-level section shapes the
    merge path expects - wrong shapes must be caught BEFORE any migration or
    merge, so a hostile section is never merged into the live config.

    Deep validation (T-136): beyond the container shapes, every structure the
    runtime actually dereferences is checked - combo entries (ComboTab indexes
    trigger/keys/interval directly), champion/minimap/afkfarm entries, toggles
    (typed against the single TOGGLE_DEFAULTS source), window and mode. Any
    JSON that passes here is safe for load_config_merge, tab constructors,
    collect_config, _show_hotkeys and AHK generation. Unknown keys are left
    alone: they are forward-compatible and nothing consumes them.
    """
    problems = []
    if not isinstance(data, dict):
        return ["root is not an object"]
    _SECTION_SHAPES = {
        "toggles": "object", "combos": "list", "champions": "object",
        "minimap": "object", "afkfarm": "object",
    }
    for key, shape in _SECTION_SHAPES.items():
        if key in data:
            ok = isinstance(data[key], dict) if shape == "object" \
                else isinstance(data[key], list)
            if not ok:
                problems.append("'%s' is not %s" % (key, shape))
                continue  # wrong container - deeper checks would mis-report
            if shape == "object":
                if key == "toggles":
                    _check_toggles(problems, data[key])
                elif key == "champions":
                    _check_champions(problems, data[key])
                elif key == "minimap":
                    _check_minimap(problems, data[key])
                elif key == "afkfarm":
                    _check_afkfarm(problems, data[key])
            else:
                _check_combos(problems, data[key])
    for key in ("mode", "lang"):
        if key in data and not isinstance(data[key], str):
            problems.append("'%s' is not a string" % key)
    if "mode" in data and isinstance(data["mode"], str) and not data["mode"]:
        problems.append("'mode' is an empty string")
    if "window" in data:
        _check_window(problems, data["window"])
    return problems


def _is_volatile(key):
    """Runtime state that belongs in the gitignored local file, not the
    committed config.json: per-champion checkbox flags and window geometry."""
    return key.startswith("enabled_") or key.startswith("toggle_")


def split_volatile(config: dict) -> tuple[dict, dict]:
    """Return (stable, local). Window geometry and per-champion runtime flags
    move to the local half; everything else stays in config.json.

    Keeps the committed config.json free of per-user state so a GUI run does
    not dirty the working tree. On load merge_volatile() puts it back.
    """
    stable = {k: v for k, v in config.items() if k != "window"}
    local = {}
    if isinstance(config.get("window"), dict) and config["window"]:
        local["window"] = config["window"]
    champs = config.get("champions")
    if isinstance(champs, dict):
        local_champs = {}
        stable_champs = {}
        for slug, entry in champs.items():
            if not isinstance(entry, dict):
                stable_champs[slug] = entry
                continue
            volatile = {k: v for k, v in entry.items() if _is_volatile(k)}
            stable_champs[slug] = {k: v for k, v in entry.items()
                                   if not _is_volatile(k)}
            if volatile:
                local_champs[slug] = volatile
        stable["champions"] = stable_champs
        if local_champs:
            local["champions"] = local_champs
    return stable, local


def _clean_window(raw):
    """Whitelist the only two window fields the app reads, with exact types:
    active_tab int (bool is int in Python - reject it), position str. Anything
    else is dropped so bad local state is ignored, never merged."""
    clean = {}
    if not isinstance(raw, dict):
        return clean
    at = raw.get("active_tab")
    if isinstance(at, int) and not isinstance(at, bool):
        clean["active_tab"] = at
    pos = raw.get("position")
    if isinstance(pos, str):
        clean["position"] = pos
    return clean


def merge_volatile(config: dict, local: dict) -> dict:
    """Overlay the gitignored runtime state back onto a loaded config.

    Total: hostile local shapes are ignored, never raised on (T-086) - the
    caller validates first, this stays defensive as the second gate.
    """
    if not isinstance(local, dict):
        return config
    window = _clean_window(local.get("window"))
    if window:
        current = config.get("window")
        if isinstance(current, dict):
            current.update(window)
        else:
            config["window"] = window
    champs = local.get("champions")
    if isinstance(champs, dict):
        cfg_champs = config.get("champions")
        if not isinstance(cfg_champs, dict):
            return config
        for slug, entry in champs.items():
            if not isinstance(entry, dict):
                continue
            target = cfg_champs.get(slug)
            if not isinstance(target, dict):
                continue
            for k, v in entry.items():
                if _is_volatile(k) and isinstance(v, bool):
                    target[k] = v
    return config


def validate_local_config(local: dict) -> list[str]:
    """Total structural check of config.local.json. Returns problem strings.

    Root must be a dict; window must be a dict with int (not bool) active_tab
    and string position; champions must be a dict of dicts whose volatile
    flags are booleans. Bad local state is ignored/recovered, never a startup
    crash (T-086)."""
    problems = []
    if not isinstance(local, dict):
        return ["local root is not an object"]
    if "window" in local:
        w = local["window"]
        if not isinstance(w, dict):
            problems.append("local 'window' is not an object")
        else:
            if "active_tab" in w and (not isinstance(w["active_tab"], int)
                                      or isinstance(w["active_tab"], bool)):
                problems.append("local window.active_tab is not an int")
            if "position" in w and not isinstance(w["position"], str):
                problems.append("local window.position is not a string")
    if "champions" in local:
        c = local["champions"]
        if not isinstance(c, dict):
            problems.append("local 'champions' is not an object")
        else:
            for slug, entry in c.items():
                if not isinstance(entry, dict):
                    problems.append("local champions.%s is not an object" % slug)
                    continue
                for k, v in entry.items():
                    if _is_volatile(k) and not isinstance(v, bool):
                        problems.append(
                            "local champions.%s.%s is not a bool" % (slug, k))
    return problems
