"""Shared engine-tab JSON I/O.

Reads distinguish missing / corrupt / io_error / wrong_shape (T-137): a file
that could not be read safely is NEVER overwritten - DeathTab and BuyTab both
read-modify-write deathwatch_config.json, and a failed read turning into {}
would let one partial subset replace the whole config.

Saves are atomic (temp + os.replace) and keep the previous content as .bak,
so an interrupted write can never truncate the live file.
"""

import copy
import json
import os
import shutil

BAK_SUFFIX = ".bak"


def read_json(path):
    """Return (data, status); status in ok/missing/corrupt/io_error/wrong_shape."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None, "missing"
    except OSError:
        return None, "io_error"
    except ValueError:
        return None, "corrupt"
    if not isinstance(data, dict):
        return None, "wrong_shape"
    return data, "ok"


def load_json(path):
    """Display-only read: missing/corrupt/unreadable/wrong-shape -> {}.

    Safe because nothing may follow it with a write: read-modify-write MUST go
    through update_json(), which refuses to overwrite a source it could not
    read safely (T-137).
    """
    data, status = read_json(path)
    return data if status == "ok" else {}


def save_json(path, data):
    """Atomic write keeping the previous content as .bak. Returns True only on
    a successful write; never raises on disk errors."""
    if not isinstance(data, dict):
        return False
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.write("\n")
        if os.path.exists(path):
            shutil.copy2(path, path + BAK_SUFFIX)
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False
    return True


def update_json(path, mutate, canonical_default=None):
    """Safe read-modify-write. `mutate(doc)` edits the loaded dict in place.

    - ok: mutate the real document, atomic write.
    - missing: if canonical_default is given, start from a deep copy of that
      COMPLETE default (never a partial {}), then mutate and write.
    - corrupt / io_error / wrong_shape: abort, return False, source untouched.

    Returns True only when a write landed.
    """
    data, status = read_json(path)
    if status == "ok":
        pass
    elif status == "missing" and canonical_default is not None:
        data = copy.deepcopy(canonical_default)
    else:
        return False
    mutate(data)
    return save_json(path, data)