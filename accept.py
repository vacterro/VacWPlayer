"""Auto-accept poller. Uses PrintWindow — works even when game behind other windows."""

import os
import sys

import cv2

import capture
import poller_engine

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "accept_config.json")


def load_config():
    return poller_engine.load_config(CONFIG_PATH, "accept_config.json")


def build_templates(cfg):
    return poller_engine.build_scaled_templates(cfg, BASE)


def _startup(cfg, targets):
    return ("watching for window '%s' with %d accept template(s), "
            "ctrl+c to stop" % (cfg["window_title"], len(targets)))


def _reload(cfg, targets):
    return "reloaded config (%d templates)" % len(targets)


def _scan(hwnd, cfg, targets):
    if poller_engine.has_regions(targets):
        return poller_engine.scan_by_region(hwnd, targets)
    try:
        full_img = capture.grab(hwnd)
    except RuntimeError:
        return None
    gray = cv2.cvtColor(full_img, cv2.COLOR_BGR2GRAY)
    for entry in targets:
        if poller_engine.click_template_match(hwnd, gray, entry):
            return True
    return False


def main(replace=False):
    poller_engine.run_poller(
        "accept", CONFIG_PATH, "accept_config.json",
        build_targets=build_templates,
        scan_targets=_scan,
        startup=_startup,
        reload_msg=_reload,
        replace=replace,
    )


if __name__ == "__main__":
    main(replace="--replace" in sys.argv)
