"""Auto-surrender poller. Uses PrintWindow — works even when game behind other windows."""

import os
import sys

import cv2

import capture
import poller_engine

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "surrender_config.json")


def load_config():
    return poller_engine.load_config(CONFIG_PATH, "surrender_config.json")


def build_templates(cfg):
    return poller_engine.build_scaled_templates(cfg, BASE)


def _startup(cfg, targets):
    mode = "accept" if cfg.get("auto_accept", True) else "decline"
    return ("watching for window '%s' with %d surrender template(s), mode=%s, "
            "ctrl+c to stop" % (cfg["window_title"], len(targets), mode))


def _reload(cfg, targets):
    mode = "accept" if cfg.get("auto_accept", True) else "decline"
    return "reloaded config (%d templates, mode=%s)" % (len(targets), mode)


def _scan(hwnd, cfg, targets):
    auto_accept = cfg.get("auto_accept", True)
    candidates = [e for e in targets
                  if (auto_accept and "accept" in e["name"].lower())
                  or (not auto_accept and "decline" in e["name"].lower())]
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


def main(replace=False):
    poller_engine.run_poller(
        "surrender", CONFIG_PATH, "surrender_config.json",
        build_targets=build_templates,
        scan_targets=_scan,
        startup=_startup,
        reload_msg=_reload,
        poll_default=5.0,
        replace=replace,
    )


if __name__ == "__main__":
    main(replace="--replace" in sys.argv)
