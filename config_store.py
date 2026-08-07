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
