import json
import os
import time

import cv2
import win32gui

import capture
import single_instance
import window_ctl

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "autocontinue_config.json")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("FATAL: failed to load autocontinue_config.json: %s" % e)
        raise SystemExit(1)


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


def main(replace=False):
    single_instance.ensure_single_instance("autocontinue", replace=replace)
    single_instance.start_parent_watchdog()
    window_ctl.set_dpi_aware()

    cfg_last_mtime = os.path.getmtime(CONFIG_PATH)
    cfg = load_config()
    hwnd = None
    loaded_window_title = cfg["window_title"]
    buttons = build_buttons(cfg)
    region_groups = group_by_region(buttons)
    loaded_buttons_raw = cfg["buttons"]
    print(f"watching for window '{loaded_window_title}' "
          f"across {len(region_groups)} screen region(s), ctrl+c to stop")

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

            if not hwnd or not win32gui.IsWindow(hwnd):
                try:
                    hwnd = capture.find_window(cfg["window_title"])
                    print(f"acquired hwnd={hwnd}")
                except RuntimeError:
                    time.sleep(1.0)
                    continue

            if cfg["buttons"] != loaded_buttons_raw:
                buttons = build_buttons(cfg)
                region_groups = group_by_region(buttons)
                loaded_buttons_raw = cfg["buttons"]
                print(f"reloaded button config ({len(buttons)} buttons, {len(region_groups)} regions)")

            if capture.is_minimized(hwnd):
                time.sleep(cfg["poll_interval_sec"])
                continue

            clicked = False
            for region, group in region_groups.items():
                needs_scan = any(b["tmpl"] is not None for b in group)
                crop = capture.grab_region(hwnd, region) if needs_scan else None
                for b in group:
                    x0, y0, x1, y1 = region
                    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
                    if b["tmpl"] is None:
                        print(f"blind-click '{b['name']}' at ({cx},{cy})")
                        window_ctl.click_at(hwnd, cx, cy, button="left")
                        clicked = True
                        break
                    score = match_score(crop, b["tmpl"])
                    if score >= b["threshold"]:
                        print(f"matched '{b['name']}' (score={score:.2f}), clicking ({cx},{cy})")
                        window_ctl.click_at(hwnd, cx, cy, button="left")
                        clicked = True
                        break
                if clicked:
                    break

            time.sleep(cfg["click_cooldown_sec"] if clicked else cfg["poll_interval_sec"])
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
