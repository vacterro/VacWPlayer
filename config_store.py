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


def read_raw(path):
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


def atomic_write(path, data):
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


def restore_backup(path):
    """Copy path + .bak over path. Returns True on success, False otherwise."""
    bak = path + BAK_SUFFIX
    try:
        shutil.copy2(bak, path)
    except (OSError, shutil.SameFileError):
        return False
    return True


def validate_config(data):
    """Light structural check. Returns list of problem strings ([] = fine).

    Not a full schema: config.json carries user-added minimap slots and
    champion entries, so a strict schema would reject valid files. This only
    catches top-level shape corruption worth surfacing to the user.
    """
    problems = []
    if not isinstance(data, dict):
        return ["root is not an object"]
    for key in ("toggles", "combos", "champions", "minimap", "afkfarm"):
        if key in data and not isinstance(data[key], (dict, list)):
            problems.append("'%s' is not an object" % key)
    for key in ("mode", "lang"):
        if key in data and not isinstance(data[key], str):
            problems.append("'%s' is not a string" % key)
    return problems


def _is_volatile(key):
    """Runtime state that belongs in the gitignored local file, not the
    committed config.json: per-champion checkbox flags and window geometry."""
    return key.startswith("enabled_") or key.startswith("toggle_")


def split_volatile(config):
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


def merge_volatile(config, local):
    """Overlay the gitignored runtime state back onto a loaded config."""
    if not isinstance(local, dict):
        return config
    if isinstance(local.get("window"), dict):
        config.setdefault("window", {}).update(local["window"])
    if isinstance(local.get("champions"), dict):
        for slug, entry in local["champions"].items():
            if isinstance(entry, dict) and isinstance(
                    config.get("champions", {}).get(slug), dict):
                config["champions"][slug].update(entry)
    return config
