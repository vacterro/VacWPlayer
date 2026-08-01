"""Auto-accept poller. Uses PrintWindow — works even when game behind other windows."""

import json
import os
import time

import cv2
import win32gui

import capture
import single_instance
import window_ctl

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "accept_config.json")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("FATAL: failed to load accept_config.json: %s" % e)
        raise SystemExit(1)


def build_templates(cfg):
    loaded = []
    for entry in cfg.get("templates", []):
        path = os.path.join(BASE, entry.get("file", ""))
        tmpl = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if tmpl is None:
            print("WARN: template not found, skipping '%s': %s" % (entry.get("name"), path))
            continue
        loaded.append({
            "name": entry.get("name", "?"),
            "gray": tmpl,
            "threshold": float(entry.get("threshold", 0.8)),
        })
    return loaded


def main(replace=False):
    single_instance.ensure_single_instance("accept", replace=replace)
    window_ctl.set_dpi_aware()

    cfg_last_mtime = os.path.getmtime(CONFIG_PATH)
    cfg = load_config()
    cfg_last_mtime = os.path.getmtime(CONFIG_PATH)
    cfg = load_config()
    hwnd = None
    loaded_window_title = cfg["window_title"]
    templates = build_templates(cfg)
    print(f"watching for window '{loaded_window_title}' with {len(templates)} accept template(s), ctrl+c to stop")

    while True:
        try:
            try:
                cur_mtime = os.path.getmtime(CONFIG_PATH)
            except OSError:
                cur_mtime = cfg_last_mtime
            if cur_mtime != cfg_last_mtime:
                cfg = load_config()
                cfg_last_mtime = cur_mtime

                if cfg["window_title"] != loaded_window_title:
                    loaded_window_title = cfg["window_title"]
                    hwnd = None
                    print(f"window title changed, now watching '{loaded_window_title}'")

                templates = build_templates(cfg)
                print(f"reloaded config ({len(templates)} templates)")

            if not hwnd or not win32gui.IsWindow(hwnd):
                try:
                    hwnd = capture.find_window(cfg["window_title"])
                    print(f"acquired hwnd={hwnd}")
                except RuntimeError:
                    time.sleep(1.0)
                    continue

            if capture.is_minimized(hwnd):
                time.sleep(cfg.get("poll_interval_sec", 1.0))
                continue

            try:
                full_img = capture.grab(hwnd)
            except RuntimeError:
                time.sleep(cfg.get("poll_interval_sec", 1.0))
                continue

            gray = cv2.cvtColor(full_img, cv2.COLOR_BGR2GRAY)
            clicked = False

            for entry in templates:
                tmpl = entry["gray"]
                if gray.shape[0] < tmpl.shape[0] or gray.shape[1] < tmpl.shape[1]:
                    continue
                result = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)
                if max_val >= entry["threshold"]:
                    th, tw = tmpl.shape
                    cx, cy = max_loc[0] + tw // 2, max_loc[1] + th // 2
                    print(f"matched '{entry['name']}' (score={max_val:.2f}), clicking ({cx},{cy})")
                    window_ctl.click_at(hwnd, cx, cy, button="left")
                    clicked = True
                    break

            time.sleep(cfg.get("click_cooldown_sec", 3.0) if clicked else cfg.get("poll_interval_sec", 1.0))
        except KeyboardInterrupt:
            print("stopped")
            break
        except Exception as e:
            print(f"lost window ({e}); will try to re-acquire...")
            hwnd = None
            time.sleep(1.0)


if __name__ == "__main__":
    import sys
    main(replace="--replace" in sys.argv)
