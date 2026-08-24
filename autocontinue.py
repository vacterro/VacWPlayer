"""Post-game continue poller. Watches region-grouped buttons via PrintWindow capture."""

import os
import sys

import cv2
import numpy as np

import capture
import poller_engine
import window_ctl

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "autocontinue_config.json")


def load_config():
    return poller_engine.load_config(CONFIG_PATH, "autocontinue_config.json")


def match_score(region_gray, template_gray):
    """Compare two grayscale crops directly - caller already converted once."""
    if region_gray.shape != template_gray.shape:
        region_gray = cv2.resize(region_gray, (template_gray.shape[1], template_gray.shape[0]))
    return cv2.matchTemplate(region_gray, template_gray, cv2.TM_CCOEFF_NORMED)[0][0]


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
    """Load every configured button template. A template that cannot be read
    DISABLES that button - it is never turned into a blind-click candidate
    (T-138): a click without visual evidence is worse than no click."""
    buttons = []
    for b in cfg["buttons"]:
        tmpl = cv2.imread(os.path.join(BASE, b["template"]), cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            print("WARN: template not found, disabling '%s': %s" % (b.get("name"), b["template"]))
            continue
        buttons.append({**b, "tmpl": tmpl})
    return buttons


def _build_targets(cfg):
    buttons = build_buttons(cfg)
    return buttons, group_by_region(buttons)


def targets_usable(targets, cfg=None):
    """True when the rebuilt target set carries at least one usable button
    (template loaded). Driven by run_poller's `usable` hook (T-138):
    startup with zero usable targets is a deterministic FATAL, and a hot
    reload producing zero usable targets keeps the last-good set."""
    return bool(targets[0])


def _startup(cfg, targets):
    return ("watching for window '%s' across %d screen region(s), "
            "ctrl+c to stop" % (cfg["window_title"], len(targets[1])))


def _reload(cfg, targets):
    return "reloaded button config (%d buttons, %d regions)" % (len(targets[0]), len(targets[1]))


def _scan(hwnd, cfg, targets):
    """W2-PERF-004: one full-frame capture per poll regardless of region count.
    W2-008: validates all regions against current client size before any
    BitBlt/crop/match - out-of-client regions are silently skipped.
    Background path uses a single PrintWindow + one BGR->gray conversion,
    then slices region crops from the coherent frame. Foreground retains
    cheap region BitBlt but still converts each region to gray only once."""
    buttons, region_groups = targets
    # W2-008: resolve current client size once and filter out-of-bounds regions.
    try:
        cw, ch = capture.get_client_size(hwnd)
    except Exception:
        cw, ch = 9999, 9999  # if we can't query, don't filter
    foreground = capture.is_foreground(hwnd)
    if foreground:
        # Foreground: cheap region BitBlt per group, one gray conversion per group.
        for region, group in region_groups.items():
            x0, y0, x1, y1 = region
            # W2-008: reject region not wholly inside current client area.
            if not (0 <= x0 < x1 <= cw and 0 <= y0 < y1 <= ch):
                continue
            bgr_crop = capture.grab_region(hwnd, region)
            gray_crop = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2GRAY)
            for b in group:
                cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                score = match_score(gray_crop, b["tmpl"])
                if score >= b["threshold"]:
                    print("matched '%s' (score=%.2f), clicking (%d,%d)" % (b["name"], score, cx, cy))
                    window_ctl.click_at(hwnd, cx, cy, button="left")
                    return True
    else:
        # Background: ONE PrintWindow, raw BGRA (no full-frame gray conversion).
        # Crop each region FIRST, then convert only that crop to gray
        # (T-W2-PERF-004): a 200x200 region no longer drags the whole 1280x720
        # frame through cvtColor.
        try:
            full_rgba = capture.grab_rgba(hwnd)
        except RuntimeError:
            return None
        for region, group in region_groups.items():
            x0, y0, x1, y1 = region
            # W2-008: reject region not wholly inside current client area.
            if not (0 <= x0 < x1 <= cw and 0 <= y0 < y1 <= ch):
                continue
            crop = np.ascontiguousarray(full_rgba[y0:y1, x0:x1])
            if crop.shape[0] < 1 or crop.shape[1] < 1:
                continue  # empty crop after resize/bounds mismatch
            gray_crop = cv2.cvtColor(crop, cv2.COLOR_BGRA2GRAY)
            for b in group:
                cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                score = match_score(gray_crop, b["tmpl"])
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
        usable=targets_usable,
        poll_default=0.6,
        replace=replace,
    )


if __name__ == "__main__":
    main(replace="--replace" in sys.argv)
