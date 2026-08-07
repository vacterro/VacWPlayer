"""Shared template-poller loop for the standalone screen-watching engines.

accept.py, surrender.py and autocontinue.py all watch a game window, poll its
capture, click a button when a template matches, reload their config when the
file changes, and take over cleanly with --replace. That lifecycle used to be
copy-pasted across the three; it lives here now. Each engine supplies its own
target builder, scan callback and user-facing messages.
"""

import json
import os
import time

import cv2
import win32gui

import capture
import engine_config
import single_instance
import window_ctl


def load_config(config_path, config_name):
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print("FATAL: failed to load %s: %s" % (config_name, e))
        raise SystemExit(1)
    return engine_config.validate_engine_config(cfg, config_name)


def build_scaled_templates(cfg, base_dir):
    """Load each template file plus 0.8/0.9/1.1/1.2 scale versions."""
    loaded = []
    for entry in cfg.get("templates", []):
        path = os.path.join(base_dir, entry.get("file", ""))
        tmpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            print("WARN: template not found, skipping '%s': %s" % (entry.get("name"), path))
            continue
        scaled_templates = [tmpl]
        for scale in [0.8, 0.9, 1.1, 1.2]:
            h, w = tmpl.shape[:2]
            scaled_templates.append(cv2.resize(tmpl, (int(w * scale), int(h * scale))))
        loaded.append({
            "name": entry.get("name", "?"),
            "templates": scaled_templates,
            "threshold": float(entry.get("threshold", 0.75)),
        })
    return loaded


def best_template_match(gray, entry):
    """Best (score, loc, template-size) over the entry's scaled templates."""
    best_score = 0
    best_loc = None
    best_tmpl_size = None
    for tmpl in entry["templates"]:
        if gray.shape[0] < tmpl.shape[0] or gray.shape[1] < tmpl.shape[1]:
            continue
        result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val > best_score:
            best_score = max_val
            best_loc = max_loc
            best_tmpl_size = tmpl.shape
    return best_score, best_loc, best_tmpl_size


def click_template_match(hwnd, gray, entry):
    """Click the best matching scaled-template location in a full-window gray image."""
    score, loc, size = best_template_match(gray, entry)
    if score < entry["threshold"] or not loc or not size:
        return False
    th, tw = size
    cx, cy = loc[0] + tw // 2, loc[1] + th // 2
    print("matched '%s' (score=%.2f), clicking (%d,%d)" % (entry["name"], score, cx, cy))
    window_ctl.click_at(hwnd, cx, cy, button="left")
    return True


def run_poller(name, config_path, config_name, build_targets, scan_targets,
               startup, reload_msg, poll_default=1.0, cooldown_default=3.0,
               replace=False):
    """Run the shared poll loop. scan_targets returns True (clicked), False (no
    match) or None (transient capture failure - retry after the poll interval)."""
    single_instance.ensure_single_instance(name, replace=replace)
    single_instance.start_parent_watchdog()
    window_ctl.set_dpi_aware()

    cfg_last_mtime = os.path.getmtime(config_path)
    cfg = load_config(config_path, config_name)
    hwnd = None
    loaded_window_title = cfg["window_title"]
    targets = build_targets(cfg)
    print(startup(cfg, targets))

    while True:
        try:
            cfg_last_mtime, changed = engine_config.mtime_changed(config_path, cfg_last_mtime)
            if changed:
                cfg = load_config(config_path, config_name)
                if cfg["window_title"] != loaded_window_title:
                    loaded_window_title = cfg["window_title"]
                    hwnd = None
                    print("window title changed, now watching '%s'" % loaded_window_title)
                targets = build_targets(cfg)
                msg = reload_msg(cfg, targets)
                if msg:
                    print(msg)

            if not hwnd or not win32gui.IsWindow(hwnd):
                try:
                    hwnd = capture.find_window(cfg["window_title"])
                    print("acquired hwnd=%s" % hwnd)
                except RuntimeError:
                    time.sleep(1.0)
                    continue

            if capture.is_minimized(hwnd):
                time.sleep(cfg.get("poll_interval_sec", poll_default))
                continue

            clicked = scan_targets(hwnd, cfg, targets)
            if clicked is None:
                time.sleep(cfg.get("poll_interval_sec", poll_default))
                continue
            time.sleep(cfg.get("click_cooldown_sec", cooldown_default) if clicked
                       else cfg.get("poll_interval_sec", poll_default))
        except KeyboardInterrupt:
            print("stopped")
            break
        except Exception as e:
            print("lost window (%s); will try to re-acquire..." % e)
            hwnd = None
            time.sleep(1.0)

