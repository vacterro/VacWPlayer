"""Config load/save with corruption guard.

config.json is user state: a corrupt file silently falling back to an empty
dict has historically overwritten every setting on the next save. This module
gives the app atomic writes with a .bak kept before every overwrite, plus a
restore path so a bad file is recovered from the last good backup instead of
dropping to defaults.
"""

import json
import os
import shutil

BAK_SUFFIX = ".bak"


def read_raw(path: str) -> tuple[object, str | None]:
    """Return (data, error). error is None, 'missing', or 'corrupt'.

    OSError covers "no file yet" (first run) and permission failures;
    ValueError covers malformed JSON. Callers treat the two differently:
    missing is normal, corrupt is data loss.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
    except OSError:
        return None, "missing"
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
    """Copy path + .bak over path. Returns True on success, False otherwise."""
    bak = path + BAK_SUFFIX
    try:
        shutil.copy2(bak, path)
    except (OSError, shutil.SameFileError):
        return False
    return True


def validate_config(data: dict) -> list[str]:
    """Total structural check. Returns list of problem strings ([] = fine).

    Never raises: malformed-but-valid JSON must be rejected or ignored, never
    crash startup (T-086). Verifies the exact top-level section shapes the
    merge path expects - wrong shapes must be caught BEFORE any migration or
    merge, so a hostile section is never merged into the live config.
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
    for key in ("mode", "lang"):
        if key in data and not isinstance(data[key], str):
            problems.append("'%s' is not a string" % key)
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
