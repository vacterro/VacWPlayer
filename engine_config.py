"""Shared engine-config reload helper.

The four engines (accept, surrender, autocontinue, deathwatch) poll their
config file's mtime each loop iteration and reload when it changes. The
check is identical in all four, so it lives here once.
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
