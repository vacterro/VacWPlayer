import json
import os
import time

import cv2
import win32gui

import capture
import digit_reader
import key_blocker
import single_instance
import window_ctl

BASE = os.path.dirname(__file__)


def load_config():
    path = os.path.join(BASE, "deathwatch_config.json")
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        print("FATAL: failed to load deathwatch_config.json: %s" % e)
        raise SystemExit(1)


def label_match_score(region_bgr, template_gray):
    crop = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    if crop.shape != template_gray.shape:
        crop = cv2.resize(crop, (template_gray.shape[1], template_gray.shape[0]))
    return cv2.matchTemplate(crop, template_gray, cv2.TM_CCOEFF_NORMED)[0][0]


def toggle_mouse_lock(hwnd=None):
    """Send BlueStacks' Ctrl+Shift+F8 mouse-lock chord.

    keybd_event is system-wide: it lands on whatever window owns keyboard
    focus. Firing it while the game is not in front planted a real Ctrl+Shift
    chord in a browser or editor - and if anything threw between the downs and
    the ups, the modifiers stayed physically down, which is what a "phantom
    stuck Shift" outside the game actually was. So: refuse unless the target
    window is genuinely in the foreground, and release in a finally block so
    the ups are unconditional.
    """
    import ctypes

    if hwnd is not None and win32gui.GetForegroundWindow() != hwnd:
        print("mouse-lock toggle skipped: game is not the foreground window")
        return False

    KEYUP = 2
    downs = [0x11, 0x10, 0x77]  # Ctrl, Shift, F8
    sent = []
    try:
        for vk in downs:
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            sent.append(vk)
        time.sleep(0.05)
        print("sent Ctrl+Shift+F8 to toggle mouse lock")
        return True
    except Exception as e:
        print(f"failed to toggle mouse lock: {e}")
        return False
    finally:
        for vk in reversed(sent):
            try:
                ctypes.windll.user32.keybd_event(vk, 0, KEYUP, 0)
            except Exception as e:
                print(f"failed to release {vk:#04x} after mouse lock: {e}")


def _set_block(sec):
    """Convenience: start or stop the pedal key block."""
    if sec > 0:
        key_blocker.block_pedals_for(sec)
    else:
        key_blocker.unblock()


def handle_death(hwnd, cfg, templates):
    print("death detected")

    pedal_block_sec = cfg.get("pedal_block_sec", 1.0)
    wants_block = pedal_block_sec > 0

    # === PHASE 0: Block pedals during critical death transition ===
    _set_block(pedal_block_sec if wants_block else 0)

    # PHASE 0 try/finally: pedals unblock even if quickbuy, timer read,
    # or minimize throws. Without this guard the block stays until
    # pedal_block_sec expires, making pedals feel dead.
    #
    # NOTE: No mouse events are sent here — every hardware mouse event
    # that reaches BlueStacks triggers its built-in mouse capture,
    # locking the physical cursor.  Stuck-movement cleanup is handled
    # by wr_runtime.ahk's NeedCleanup mechanism when focus returns.
    try:
        vk = window_ctl.key_vk(cfg["quickbuy_key"])
        sent = window_ctl.press_key_burst(
            hwnd, vk, cfg["quickbuy_presses"], cfg["quickbuy_window_ms"]
        )
        if sent:
            print(f"quick-buy: sent '{cfg['quickbuy_key']}' x{cfg['quickbuy_presses']}")
        else:
            print("quick-buy skipped: BlueStacks isn't the focused window right now")

        print("waiting shop buffer")
        time.sleep(cfg["shop_buffer_sec"])

        digits_crop = capture.grab_region(hwnd, cfg["timer_digits_region"])
        n = digit_reader.read_number(digits_crop, templates)

        if n is None:
            print("could not read respawn timer, skipping minimize for this death")
            return

        wait = n - cfg["shop_buffer_sec"] - cfg["restore_buffer_sec"]
        wait = max(0.0, min(wait, cfg["max_death_wait_sec"]))

        work_hwnd = None
        if cfg.get("switch_to_work_window") and cfg.get("work_window_title"):
            try:
                work_hwnd = capture.find_window(cfg["work_window_title"])
            except RuntimeError:
                print(f"work window '{cfg['work_window_title']}' not found, skipping switch")

        import win32gui
        # No mouse events here — they trigger BlueStacks mouse capture.
        # wr.ahk's NeedCleanup handles stuck LMB/RMB on focus return.
        if cfg.get("lock_window_resurrect"):
            print("unlocking mouse before minimizing...")
            toggle_mouse_lock(hwnd)

        print(f"respawn in {n}s, minimizing for {wait:.1f}s")
        # Drop any button wr_runtime.ahk is still holding for the movement
        # remap first: posted messages, so no hardware event and no BlueStacks
        # cursor capture. Doing it before the minimize means the game is not
        # left walking into a wall for the whole respawn timer.
        window_ctl.release_mouse_buttons(hwnd)
        window_ctl.minimize(hwnd)
    finally:
        # === UNBLOCK immediately after minimize ===
        _set_block(0)
        print("phase-0 finished, pedals unblocked")

    if work_hwnd:
        window_ctl.switch_to(work_hwnd)
        print(f"switched to work window '{cfg['work_window_title']}'")
        
    print(f"waiting {wait:.1f}s, spilling pedals suppressed")
    if wants_block:
        key_blocker.block_until_released()
        
    user_aborted = False
    t_end = time.time() + wait
    settle_time = time.time() + 2.0
    while time.time() < t_end:
        time.sleep(1.0)
        if time.time() > settle_time and not win32gui.IsIconic(hwnd) and win32gui.GetForegroundWindow() == hwnd:
            print("user manually focused game, aborting automation")
            user_aborted = True
            break
            
    if user_aborted:
        _set_block(0)
        return
        
    if work_hwnd:
        window_ctl.minimize(work_hwnd)

    # === PHASE 3: Block during restore to catch pedal spam ===
    _set_block(pedal_block_sec if wants_block else 0)

    # PHASE 3 try/finally: separate guard so a failure in
    # maximize_and_focus or resurrect actions never leaks the block.
    try:
        window_ctl.maximize_and_focus(hwnd)
        print("restored and focused")

        if win32gui.GetForegroundWindow() == hwnd:
            if cfg.get("click_mid_on_resurrect"):
                try:
                    with open(os.path.join(BASE, "config.json")) as f:
                        main_cfg = json.load(f)
                    mid = main_cfg.get("minimap", {}).get("mid", {})
                    if "x" in mid and "y" in mid:
                        window_ctl.click_client_pos(hwnd, mid["x"], mid["y"])
                        print(f"clicked mid on minimap ({mid['x']}, {mid['y']})")
                except Exception as e:
                    print(f"failed to click mid: {e}")

            if cfg.get("lock_window_resurrect"):
                toggle_mouse_lock(hwnd)
        else:
            print("resurrect actions skipped: game not focused after restore")
    finally:
        _set_block(0)
        print("phase-3 finished, pedals unblocked")


def main(replace=False):
    single_instance.ensure_single_instance("deathwatch", replace=replace)
    single_instance.start_parent_watchdog()
    window_ctl.set_dpi_aware()
    cfg_path = os.path.join(BASE, "deathwatch_config.json")
    cfg = load_config()
    key_blocker.start(cfg.get("blocked_keys", []))
    try:
        cfg_last_mtime = 0.0
        loaded_window_title = ""
        loaded_digits_dir = ""
        loaded_label_path = ""

        cfg_last_mtime = os.path.getmtime(cfg_path)
        hwnd = None
        loaded_window_title = cfg["window_title"]
        templates = digit_reader.load_templates(os.path.join(BASE, cfg["digit_templates_dir"]))
        loaded_digits_dir = cfg["digit_templates_dir"]
        was_dead = False
        print(f"watching for window '{loaded_window_title}'...")
        label_template = cv2.imread(os.path.join(BASE, cfg["death_label_template"]), cv2.IMREAD_GRAYSCALE)
        if label_template is None:
            print("FATAL: death label template not found: %s" % cfg["death_label_template"])
            return
        loaded_label_path = cfg["death_label_template"]
        print(f"watching hwnd={hwnd}, ctrl+c to stop")

        was_dead = False
        while True:
            try:
                try:
                    cur_mtime = os.path.getmtime(cfg_path)
                except OSError:
                    cur_mtime = cfg_last_mtime
                if cur_mtime != cfg_last_mtime:
                    with open(cfg_path) as f:
                        cfg = json.load(f)
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

                if capture.is_minimized(hwnd):
                    time.sleep(cfg["poll_interval_sec"])
                    continue

                if cfg["digit_templates_dir"] != loaded_digits_dir:
                    templates = digit_reader.load_templates(os.path.join(BASE, cfg["digit_templates_dir"]))
                    loaded_digits_dir = cfg["digit_templates_dir"]
                    print("reloaded digit templates")

                if cfg["death_label_template"] != loaded_label_path:
                    label_template = cv2.imread(os.path.join(BASE, cfg["death_label_template"]), cv2.IMREAD_GRAYSCALE)
                    loaded_label_path = cfg["death_label_template"]
                    print("reloaded death label template")

                if capture.is_minimized(hwnd):
                    time.sleep(cfg["poll_interval_sec"])
                    continue

                label_crop = capture.grab_region(hwnd, cfg["death_label_region"])
                score = label_match_score(label_crop, label_template)
                is_dead = score >= cfg["match_threshold"]

                if is_dead and not was_dead:
                    was_dead = True
                    handle_death(hwnd, cfg, templates)
                elif not is_dead and was_dead:
                    was_dead = False
                    print("respawn confirmed")

                time.sleep(cfg["poll_interval_sec"])
            except KeyboardInterrupt:
                print("stopped")
                break
            except Exception as e:
                print(f"lost window ({e}); will try to re-acquire...")
                was_dead = False
                hwnd = None
                time.sleep(1.0)
    finally:
        key_blocker.stop()


if __name__ == "__main__":
    import sys

    main(replace="--replace" in sys.argv)
