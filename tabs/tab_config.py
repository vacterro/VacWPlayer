"""Shared engine-tab JSON I/O.

Reads distinguish missing / corrupt / io_error / wrong_shape (T-137): a file
that could not be read safely is NEVER overwritten - DeathTab and BuyTab both
read-modify-write deathwatch_config.json, and a failed read turning into {}
would let one partial subset replace the whole config.

Saves are atomic (temp + os.replace) and keep the previous content as .bak,
so an interrupted write can never truncate the live file.

When a `config_name` is known (T-152), the GUI path also runs the engine's own
semantic validation: nested garbage that parses as JSON ({"templates":{"x":1}})
is NOT "ok" for the GUI - display falls back to canonical defaults and
read-modify-write refuses, so a tab can never crash on item.get()/iteration or
persist a config the engine itself would reject.
"""

import copy
import json
import os

import engine_config

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


def load_json(path, config_name=None):
    """Display-only read: missing/corrupt/unreadable/wrong-shape - or, when a
    config_name is given, semantically invalid per the engine's own validator
    (T-152) - -> {} (tabs then fall back to canonical display defaults).

    Safe because nothing may follow it with a write: read-modify-write MUST go
    through update_json(), which refuses to overwrite a source it could not
    read safely (T-137) or that the engine would reject (T-152).

    Returns (data, status) so callers can distinguish missing (materialize
    complete canonical before honoring monitor flag) from corrupt/invalid
    (force monitor OFF, no child start) (T-CORE-012).
    """
    data, status = read_json(path)
    if status != "ok":
        return {}, status
    if config_name is not None and engine_config.semantic_problems(data, config_name):
        return {}, "semantic_invalid"
    return data, "ok"


def save_json(path, data):
    """Atomic write keeping the previous content as .bak. Returns True only on
    a successful write; never raises on disk errors."""
    if not isinstance(data, dict):
        return False
    from config_store import _atomic_replace_bytes
    try:
        raw = (json.dumps(data, indent=2) + "\n").encode("utf-8")
        _atomic_replace_bytes(path, raw, True)
    except OSError:
        tmp = path + ".tmp"
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False
    return True


def update_json(path, mutate, canonical_default=None, config_name=None):
    """Safe read-modify-write. `mutate(doc)` edits the loaded dict in place.

    - ok: validate the source semantically (when config_name is given); if the
      engine would reject it, abort - a GUI must never RMW over a config its
      own engine refuses (T-152).
    - missing: if canonical_default is given, start from a deep copy of that
      COMPLETE default (never a partial {}), then mutate and write.
    - corrupt / io_error / wrong_shape: abort, return False, source untouched.

    The candidate is validated again AFTER mutate, BEFORE the atomic write: a
    mutate that produces a config the engine would reject never lands.

    Returns True only when a write landed.
    """
    data, status = read_json(path)
    if status == "ok":
        if config_name is not None and engine_config.semantic_problems(data, config_name):
            return False
    elif status == "missing" and canonical_default is not None:
        data = copy.deepcopy(canonical_default)
    else:
        return False
    mutate(data)
    if config_name is not None and engine_config.semantic_problems(data, config_name):
        return False
    return save_json(path, data)