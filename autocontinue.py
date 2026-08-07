"""Post-game continue poller. Watches region-grouped buttons via PrintWindow capture."""

import os
import sys

import cv2

import capture
import poller_engine
import window_ctl

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "autocontinue_config.json")


def load_config():
    return poller_engine.load_config(CONFIG_PATH, "autocontinue_config.json")


def match_score(region_bgr, template_gray):
    crop = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    if crop.shape != template_gray.shape:
        crop = cv2.resize(crop, (template_gray.shape[1], template_gray.shape[0]))
    return cv2.matchTemplate(crop, template_gray, cv2.TM_CCOEFF_NORMED)[0][0]


def group_by_region(buttons):
    """Several buttons (e.g. continue_shared/continue_awards) can share the same
    on-screen region across different post-game screens - capture that region
    once per poll instead of once per button."""
    groups = {}
    for b in buttons:
        key = tuple(b["region"])
        groups.setdefault(key, []).append(b)
    return groups


def build_buttons(cfg):
    buttons = []
    for b in cfg["buttons"]:
        tmpl = cv2.imread(os.path.join(BASE, b["template"]), cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            print("WARN: template not found, '%s' - blind click mode: %s" % (b.get("name"), b["template"]))
            buttons.append({**b, "tmpl": None})
            continue
        buttons.append({**b, "tmpl": tmpl})
    return buttons


def _build_targets(cfg):
    buttons = build_buttons(cfg)
    return buttons, group_by_region(buttons)


def _startup(cfg, targets):
    return ("watching for window '%s' across %d screen region(s), "
            "ctrl+c to stop" % (cfg["window_title"], len(targets[1])))


def _reload(cfg, targets):
    return "reloaded button config (%d buttons, %d regions)" % (len(targets[0]), len(targets[1]))


def _scan(hwnd, cfg, targets):
    buttons, region_groups = targets
    for region, group in region_groups.items():
        needs_scan = any(b["tmpl"] is not None for b in group)
        crop = capture.grab_region(hwnd, region) if needs_scan else None
        for b in group:
            x0, y0, x1, y1 = region
            cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
            if b["tmpl"] is None:
                print("blind-click '%s' at (%d,%d)" % (b["name"], cx, cy))
                window_ctl.click_at(hwnd, cx, cy, button="left")
                return True
            score = match_score(crop, b["tmpl"])
            if score >= b["threshold"]:
                print("matched '%s' (score=%.2f), clicking (%d,%d)" % (b["name"], score, cx, cy))
                window_ctl.click_at(hwnd, cx, cy, button="left")
                return True
    return False


def main(replace=False):
    poller_engine.run_poller(
        "autocontinue", CONFIG_PATH, "autocontinue_config.json",
        build_targets=_build_targets,
        scan_targets=_scan,
        startup=_startup,
        reload_msg=_reload,
        poll_default=0.6,
        replace=replace,
    )


if __name__ == "__main__":
    main(replace="--replace" in sys.argv)
