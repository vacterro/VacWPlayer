"""Auto-surrender poller. Uses PrintWindow — works even when game behind other windows."""

import os
import sys

import cv2

import capture
import engine_config
import poller_engine

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "surrender_config.json")
SURRENDER_DEFAULTS = engine_config.canonical_default("surrender_config.json")


def load_config():
    return poller_engine.load_config(CONFIG_PATH, "surrender_config.json")


def build_templates(cfg):
    return poller_engine.build_scaled_templates(cfg, BASE)


def _startup(cfg, targets):
    mode = "accept" if cfg.get("auto_accept", SURRENDER_DEFAULTS["auto_accept"]) else "decline"
    return ("watching for window '%s' with %d surrender template(s), mode=%s, "
            "ctrl+c to stop" % (cfg["window_title"], len(targets), mode))


def _reload(cfg, targets):
    mode = "accept" if cfg.get("auto_accept", SURRENDER_DEFAULTS["auto_accept"]) else "decline"
    return "reloaded config (%d templates, mode=%s)" % (len(targets), mode)


def targets_usable(targets, cfg=None):
    """True when at least one loaded target is present (T-W2-006). Kept for
    backward-compat with run_poller's (targets, cfg) call shape; surrender
    now uses _targets_usable_with_cfg (mode-aware) instead."""
    return bool(targets)


def _scan(hwnd, cfg, targets):
    action = "accept" if cfg.get("auto_accept", SURRENDER_DEFAULTS["auto_accept"]) else "decline"
    candidates = [e for e in targets if e.get("action") == action]
    if poller_engine.has_regions(candidates):
        return poller_engine.scan_by_region(hwnd, candidates)
    try:
        full_img = capture.grab(hwnd)
    except RuntimeError:
        return None
    gray = cv2.cvtColor(full_img, cv2.COLOR_BGR2GRAY)
    for entry in candidates:
        if poller_engine.click_template_match(hwnd, gray, entry):
            return True
    return False


def _targets_usable_with_cfg(targets, cfg):
    """W2-003: usable only when at least one target matches configured action."""
    auto_accept = cfg.get("auto_accept", SURRENDER_DEFAULTS["auto_accept"])
    action = "accept" if auto_accept else "decline"
    return bool([e for e in targets if e.get("action") == action])


def main(replace=False):
    poller_engine.run_poller(
        "surrender", CONFIG_PATH, "surrender_config.json",
        build_targets=build_templates,
        scan_targets=_scan,
        startup=_startup,
        reload_msg=_reload,
        usable=_targets_usable_with_cfg,
        replace=replace,
    )


if __name__ == "__main__":
    main(replace="--replace" in sys.argv)
