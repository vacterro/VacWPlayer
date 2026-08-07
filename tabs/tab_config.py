"""Shared engine-tab JSON I/O.

Replaces the per-tab copy-pasted load_json/save_json. Load is total: missing,
corrupt or wrong-shape JSON yields {} instead of raising, so a tab constructor
never crashes on a bad config file. Save is atomic (temp + os.replace) so a
crash mid-write can never truncate an engine config.
"""

import json
import os


def load_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_json(path, data):
    if not isinstance(data, dict):
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)
