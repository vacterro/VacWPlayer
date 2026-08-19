"""Shared engine-config reload + validation helper.

The four engines (accept, surrender, autocontinue, deathwatch) poll their
config file's mtime each loop iteration and reload when it changes, and each
must survive wrong-typed config values loudly instead of crashing mid-loop.
Both checks are identical in all four, so they live here once.

The validator is TOTAL: it gathers problems without ever throwing on a
malformed value (no int()/float() on unchecked objects, bool is never numeric,
numerics must be finite). The load path turns any problems into the existing
FATAL SystemExit policy.
"""

import copy
import logging
import math
import os
import re

logger = logging.getLogger(__name__)


def setup_logging(level: int = logging.INFO) -> None:
    """Configure the root logger once (console). Engines and the GUI call
    this at startup so silent-catch paths have somewhere to be heard."""
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def mtime_changed(path: str, last_mtime: float) -> tuple[float, bool]:
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


# Which single-instance/engine key map is real: blocked keys are F13-F24
# (key_blocker.VK_MAP), and the quickbuy key is a single letter/digit or a
# vkNN hex code (window_ctl.key_vk / the AHK autobuy block).
_BLOCKED_KEY_NAMES = frozenset("F%d" % n for n in range(13, 25))
_QUICKBUY_KEY_RE = re.compile(r"^vk[0-9a-fA-F]{1,2}$")

# Canonical defaults per engine config (T-137/T-141): the ONE source used by
# first-run config creation, GUI initial fallbacks, Reset and tests. Values
# are the engine-required contract plus the env-neutral shipped file values;
# machine-specific fields (window_title) start empty.
ENGINE_DEFAULTS = {
    "accept_config.json": {
        "monitor_enabled": False,
        "window_title": "",
        "poll_interval_sec": 1.0,
        "click_cooldown_sec": 3.0,
        "templates": [],
    },
    "surrender_config.json": {
        "monitor_enabled": False,
        "window_title": "",
        "poll_interval_sec": 5.0,
        "click_cooldown_sec": 3.0,
        "auto_accept": True,
        "templates": [
            {"name": "Accept", "file": "templates/sur_accept.png",
             "threshold": 0.75},
            {"name": "Decline", "file": "templates/sur_decline.png",
             "threshold": 0.75},
        ],
    },
    "autocontinue_config.json": {
        "monitor_enabled": False,
        "window_title": "",
        "poll_interval_sec": 0.6,
        "click_cooldown_sec": 2.5,
        "buttons": [
            {"name": "continue_victory",
             "region": [800, 690, 1140, 765],
             "template": "templates/buttons/continue_victory.png",
             "threshold": 0.85},
            {"name": "continue_shared",
             "region": [1590, 875, 1900, 940],
             "template": "templates/buttons/continue_shared.png",
             "threshold": 0.85},
            {"name": "continue_awards",
             "region": [1590, 875, 1900, 940],
             "template": "templates/buttons/continue_awards.png",
             "threshold": 0.85},
        ],
    },
    "deathwatch_config.json": {
        "monitor_enabled": True,
        "window_title": "",
        "poll_interval_sec": 0.4,
        "shop_buffer_sec": 0.0,
        "restore_buffer_sec": 0.0,
        "match_threshold": 0.75,
        "death_label_region": [900, 118, 1165, 145],
        "timer_digits_region": [955, 143, 1035, 170],
        "death_label_template": "templates/death_label.png",
        "digit_templates_dir": "templates/digits",
        "max_death_wait_sec": 90.0,
        "quickbuy_key": "Z",
        "quickbuy_presses": 5,
        "quickbuy_window_ms": 10.0,
        "blocked_keys": ["F13", "F14", "F15"],
        "pedal_block_sec": 5.0,
        "switch_to_work_window": False,
        "work_window_title": "",
        "click_mid_on_resurrect": False,
        "lock_window_resurrect": False,
        "cursor_move_on_resurrect": True,
        "cursor_move_x_pct": 75,
        "cursor_move_y_pct": 25,
        "cursor_move_hold_ms": 250,
        "pvp_after_resurrect": False,
        "autobuy_after_b": False,
        "buy_after_b_delay_sec": 6.5,
        "autobuy_then_mid": False,
        "autobuy_then_mid_delay_sec": 0.5,
        "controlsend_z": False,
    },
}


def canonical_default(config_name: str) -> dict:
    """Complete canonical config for an engine, deep-copied so callers may
    mutate it freely (T-159) - nested buttons/templates/regions included."""
    return copy.deepcopy(ENGINE_DEFAULTS.get(config_name, {}))


# Per-engine REQUIRED contracts (T-139): the keys each engine's runtime indexes
# WITHOUT .get(). A config missing one of these would crash mid-loop, so it is
# a FATAL validation error - not an "only validate when present" case. Keys
# beyond this list stay optional for backward compatibility.
ENGINE_REQUIRED_KEYS = {
    "accept_config.json": ("window_title",),
    "surrender_config.json": ("window_title",),
    "autocontinue_config.json": ("window_title", "buttons"),
    "deathwatch_config.json": (
        "window_title", "poll_interval_sec", "quickbuy_key",
        "quickbuy_presses", "quickbuy_window_ms", "shop_buffer_sec",
        "timer_digits_region", "restore_buffer_sec", "max_death_wait_sec",
        "digit_templates_dir", "death_label_template", "death_label_region",
        "match_threshold",
    ),
}


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _is_finite(v):
    return _is_number(v) and math.isfinite(v)


def _is_pixel_int(v):
    """A pixel coordinate is a non-bool integer (T-151): bools pass isinstance
    int, floats are not coordinates, and click_at feeds these straight into
    MAKELONG which needs integer coords."""
    return isinstance(v, int) and not isinstance(v, bool)


def quickbuy_key_vk(key) -> int | None:
    """Canonical quickbuy-key parser (T-140): one source for both the validator
    and the runtime.

    Accepts exactly what keybd_event can use - a single ASCII letter/digit
    (VK = its uppercase code point) or a vkNN hex code. Returns None for
    anything else, including non-ASCII letters like 'Ж' whose ord() is not a
    real virtual-key code and would be garbage in keybd_event.
    """
    if not isinstance(key, str) or not key:
        return None
    if len(key) == 1 and key.isascii() and key.isalnum():
        return ord(key.upper())
    if _QUICKBUY_KEY_RE.fullmatch(key):
        return int(key[2:], 16)
    return None


def _valid_quickbuy_key(k):
    return quickbuy_key_vk(k) is not None


def _collect_problems(cfg, name):
    """Total semantic validation. Returns a list of problem strings; never
    raises, whatever hostile values the JSON carries."""
    problems = []
    if not isinstance(cfg, dict):
        return ["config root is not a JSON object"]

    def _p(fmt, *args):
        problems.append(("%s: " + fmt) % ((name,) + args))

    for key in ENGINE_REQUIRED_KEYS.get(name, ()):
        if key not in cfg:
            _p("missing required key %r (runtime indexes it without a default)",
               key)

    def _check_bool(key):
        if key in cfg and not isinstance(cfg[key], bool):
            _p("key %r must be a boolean, got %r", key, cfg[key])

    def _check_str(key):
        if key in cfg and not isinstance(cfg[key], str):
            _p("key %r must be a string, got %r", key, cfg[key])

    def _check_number(key, minimum=None, positive=False):
        if key not in cfg:
            return
        v = cfg[key]
        if not _is_finite(v):
            _p("key %r must be a finite number, got %r", key, v)
            return
        if minimum is not None and v < minimum:
            _p("key %r must be >= %s, got %r", key, minimum, v)
            return
        if positive and v <= 0:
            _p("key %r must be positive, got %r", key, v)

    def _check_region(key):
        if key not in cfg:
            return
        r = cfg[key]
        if not isinstance(r, list) or len(r) != 4 or not all(_is_pixel_int(x) for x in r):
            _p("key %r must be a list of exactly 4 integer pixels, got %r", key, r)
            return
        x0, y0, x1, y1 = r
        if x1 <= x0 or y1 <= y0:
            _p("key %r region must satisfy x1>x0 and y1>y0, got %r", key, r)

    def _check_template_list(key):
        if key not in cfg:
            return
        items = cfg[key]
        if not isinstance(items, list):
            _p("key %r must be a list, got %r", key, items)
            return
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                _p("key %r[%d] must be an object, got %r", key, i, item)
                continue
            if "name" in item and not isinstance(item["name"], str):
                _p("key %r[%d].name must be a string, got %r", key, i, item["name"])
            if "file" in item and not isinstance(item["file"], str):
                _p("key %r[%d].file must be a string, got %r", key, i, item["file"])
            if "template" in item and not isinstance(item["template"], str):
                _p("key %r[%d].template must be a string, got %r", key, i, item["template"])
            if "threshold" in item:
                t = item["threshold"]
                if not _is_finite(t) or not (0.0 <= t <= 1.0):
                    _p("key %r[%d].threshold must be a finite number in 0..1, got %r",
                       key, i, t)
            if "region" in item:
                r = item["region"]
                if not isinstance(r, list) or len(r) != 4 or not all(_is_pixel_int(x) for x in r):
                    _p("key %r[%d].region must be a list of exactly 4 integer "
                       "pixels, got %r", key, i, r)
                else:
                    x0, y0, x1, y1 = r
                    if x1 <= x0 or y1 <= y0:
                        _p("key %r[%d].region must satisfy x1>x0 and y1>y0, got %r",
                           key, i, r)

    def _check_autocontinue_buttons():
        """T-151: autocontinue's build_buttons/group_by_region/_scan index
        b["template"], b["region"], b["threshold"] and b["name"] directly, so
        every configured button must carry them (generic .get()-based template
        checks would let [{}] through). accept/surrender read via .get() and
        keep their loose optional fields."""
        items = cfg.get("buttons")
        if not isinstance(items, list):
            return  # generic check already flagged the non-list
        for i, b in enumerate(items):
            if not isinstance(b, dict):
                continue  # generic check flagged
            for fld in ("name", "template"):
                v = b.get(fld)
                if not (isinstance(v, str) and v.strip()):
                    _p("key 'buttons'[%d].%s must be a non-empty string, got %r",
                       i, fld, v)
            r = b.get("region")
            if not (isinstance(r, list) and len(r) == 4
                    and all(_is_pixel_int(x) for x in r)):
                _p("key 'buttons'[%d].region is required: exactly 4 integer "
                   "pixels, got %r", i, r)
            t = b.get("threshold")
            if not (_is_finite(t) and 0.0 <= t <= 1.0):
                _p("key 'buttons'[%d].threshold is required: a finite number "
                   "in 0..1, got %r", i, t)

    # Shared surface across the poller engines and deathwatch.
    _check_bool("monitor_enabled")
    _check_str("window_title")
    _check_str("work_window_title")
    _check_str("death_label_template")
    _check_str("digit_templates_dir")
    _check_number("poll_interval_sec", positive=True)
    _check_number("click_cooldown_sec", minimum=0)
    _check_number("shop_buffer_sec", minimum=0)
    _check_number("restore_buffer_sec", minimum=0)
    _check_number("match_threshold", minimum=0)
    _check_template_list("templates")
    _check_template_list("buttons")
    if name == "autocontinue_config.json":
        _check_autocontinue_buttons()
    if name == "surrender_config.json":
        # T-CORE-014: migrate legacy template names to explicit action field.
        items = cfg.get("templates")
        if isinstance(items, list):
            for i, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                action = item.get("action")
                name_val = item.get("name", "")
                if action is not None:
                    if action not in ("accept", "decline"):
                        _p("key 'templates'[%d].action must be 'accept' or 'decline', got %r",
                           i, action)
                    continue
                low = name_val.lower()
                migrated = False
                if low == "accept":
                    items[i]["action"] = "accept"
                    migrated = True
                elif low == "decline":
                    items[i]["action"] = "decline"
                    migrated = True
                if not migrated and ("accept" in low or "decline" in low):
                    _p("key 'templates'[%d].name %r is ambiguous; add explicit action",
                       i, name_val)

    # Deathwatch-specific fields - every consumed value is validated.
    _check_region("death_label_region")
    _check_region("timer_digits_region")
    _check_number("max_death_wait_sec", positive=True)
    _check_number("pedal_block_sec", minimum=0)
    _check_number("quickbuy_window_ms", minimum=0)
    _check_number("buy_after_b_delay_sec", minimum=0)
    _check_number("autobuy_then_mid_delay_sec", minimum=0)
    for key in ("switch_to_work_window", "click_mid_on_resurrect",
                "lock_window_resurrect", "autobuy_after_b", "autobuy_then_mid",
                "controlsend_z"):
        _check_bool(key)

    if "quickbuy_presses" in cfg:
        v = cfg["quickbuy_presses"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 1:
            _p("key 'quickbuy_presses' must be a positive integer, got %r", v)

    if "quickbuy_key" in cfg and not _valid_quickbuy_key(cfg["quickbuy_key"]):
        _p("key 'quickbuy_key' must be a single letter/digit or vkNN hex, got %r",
           cfg["quickbuy_key"])

    if "blocked_keys" in cfg:
        bk = cfg["blocked_keys"]
        if not isinstance(bk, list):
            _p("key 'blocked_keys' must be a list, got %r", bk)
        else:
            for k in bk:
                if not (isinstance(k, str) and k.upper() in _BLOCKED_KEY_NAMES):
                    _p("key 'blocked_keys' item %r is not a supported F13-F24 key", k)

    if "match_threshold" in cfg and _is_finite(cfg["match_threshold"]):
        t = cfg["match_threshold"]
        if not (0.0 <= t <= 1.0):
            _p("key 'match_threshold' must be in 0..1, got %r", t)

    return problems


def validate_engine_config(cfg: dict, config_name: str) -> dict:
    """Semantically validate an engine config after json.load; exit on any
    problem.

    Mirrors the corrupt-JSON FATAL path: a bad config value is a config
    error, not something the engine can keep running through, so it prints
    the same FATAL line and raises SystemExit(1). Total by construction -
    the problem-gatherer above never throws.
    """
    problems = _collect_problems(cfg, config_name)
    if problems:
        print("FATAL: failed to load %s: %s" % (config_name, "; ".join(problems)))
        raise SystemExit(1)
    return cfg


def semantic_problems(cfg: dict, config_name: str) -> list[str]:
    """Non-exiting semantic problem collector (T-152): the SAME validation the
    engines FATAL on, exposed for the GUI read path. The GUI must not
    duplicate engine validation - it consumes this one, and a config with
    problems is display-canonical + write-refused instead of engine-FATAL."""
    return _collect_problems(cfg, config_name)
