"""Shared engine-config reload + validation helper.

The four engines (accept, surrender, autocontinue, deathwatch) poll their
config file's mtime each loop iteration and reload when it changes, and each
must survive wrong-typed config values loudly instead of crashing mid-loop.
Both checks are identical in all four, so they live here once.
"""

import os


def mtime_changed(path, last_mtime):
    """Return (current_mtime, changed) for a config file's mtime probe.

    A missing/unreadable file keeps the last known mtime and reports no
    change: the engine keeps running on the config it already loaded
    instead of erroring or reloading in a tight loop.
    """
    try:
        cur = os.path.getmtime(path)
    except OSError:
        return last_mtime, False
    return cur, cur != last_mtime


# Expected JSON types per engine-config key. Absent keys are fine (optional);
# present keys of the wrong type previously loaded silently and crashed the
# engine mid-loop (time.sleep("abc") TypeError, find_window(12345)).
_CFG_TYPES = {
    "monitor_enabled": bool,
    "auto_accept": bool,
    "window_title": str,
    "work_window_title": str,
    "death_label_template": str,
    "poll_interval_sec": (int, float),
    "click_cooldown_sec": (int, float),
    "shop_buffer_sec": (int, float),
    "restore_buffer_sec": (int, float),
    "match_threshold": (int, float),
    "templates": list,
    "buttons": list,
    "death_label_region": list,
    "timer_digits_region": list,
}


def validate_engine_config(cfg, config_name):
    """Type-check an engine config after json.load; exit on wrong types.

    Mirrors the corrupt-JSON FATAL path: a wrong-typed value is a config
    error, not something the engine can keep running through, so it prints
    the same FATAL line and raises SystemExit(1).
    """
    if not isinstance(cfg, dict):
        print("FATAL: failed to load %s: config root is not a JSON object" % config_name)
        raise SystemExit(1)
    for key, expected in _CFG_TYPES.items():
        if key not in cfg:
            continue
        value = cfg[key]
        if expected is bool:
            ok = isinstance(value, bool)
            why = "must be a boolean"
        elif isinstance(expected, tuple):
            # bool is a subclass of int in Python - reject it for numerics.
            ok = not isinstance(value, bool) and isinstance(value, expected)
            why = "must be numeric"
        else:
            ok = isinstance(value, expected)
            why = "must be %s" % expected.__name__
        if not ok:
            print("FATAL: failed to load %s: key %r %s, got %r"
                  % (config_name, key, why, value))
            raise SystemExit(1)
    return cfg
