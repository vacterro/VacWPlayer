import json
import os
import time

import cv2
import win32gui

import capture
import config_store
import digit_reader
import engine_config
import key_blocker
import single_instance
import window_ctl

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "deathwatch_config.json")


def load_config():
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except (OSError, ValueError) as e:
        print("FATAL: failed to load deathwatch_config.json: %s" % e)
        raise SystemExit(1)
    return engine_config.validate_engine_config(cfg, "deathwatch_config.json")


def label_match_score(region_bgr, template_gray):
    crop = cv2.cvtColor(region_bgr, cv2.COLOR_BGR2GRAY)
    if crop.shape != template_gray.shape:
        crop = cv2.resize(crop, (template_gray.shape[1], template_gray.shape[0]))
    return cv2.matchTemplate(crop, template_gray, cv2.TM_CCOEFF_NORMED)[0][0]


def toggle_mouse_lock(hwnd=None):
    """Send the emulator's mouse-lock chord (Ctrl+Shift+F8).

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


def _grab_safe(hwnd, region):
    """Occlusion-safe region read (T-153): foreground -> cheap BitBlt fast
    path, otherwise PrintWindow + crop. NO death decision (is_dead / timer OCR)
    may ever be computed from another application's topmost desktop pixels."""
    if capture.is_foreground(hwnd):
        return capture.grab_region(hwnd, region)
    return capture.grab_client_region(hwnd, region)


def _mid_click_coords():
    """Validated minimap-mid client coordinates from the main config (T-178).

    The main config is read through the shared validator (config_store) - no
    raw json.load shortcut that bypasses recovery/validation. Returns None for
    any missing/corrupt/invalid/wrong-typed/negative value: UNKNOWN => NO
    ACTION, coordinates are never defaulted or fabricated.
    """
    try:
        with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or config_store.validate_config(data):
        return None
    mid = (data.get("minimap") or {}).get("mid")
    if not isinstance(mid, dict):
        return None
    x, y = mid.get("x"), mid.get("y")
    if not (isinstance(x, int) and not isinstance(x, bool)
            and isinstance(y, int) and not isinstance(y, bool)
            and x >= 0 and y >= 0):
        return None
    return x, y


def _client_bounds_ok(hwnd, x, y):
    """True only when (x, y) lies inside the target's CURRENT client area -
    checked immediately before any click (T-178); a read failure is False."""
    try:
        w, h = capture.get_client_size(hwnd)
    except Exception:
        return False
    return 0 <= x < w and 0 <= y < h


def _wait_foreground(hwnd, timeout=3.0, settle=0.2):
    """Wait until `hwnd` is genuinely the foreground window, then settle.

    SetForegroundWindow can win the race ahead of the window's input routing
    actually switching (T-202): an action fired the instant the check passes
    can still land in whatever was in front a moment before. Polling until the
    foreground check holds, plus a settle pause, makes every resurrect action
    land inside the game window. False = never became foreground (or a probe
    failed) - callers must skip, never force.
    """
    t_end = time.time() + timeout
    while time.time() < t_end:
        try:
            if win32gui.GetForegroundWindow() == hwnd:
                time.sleep(settle)
                return True
        except Exception:
            return False
        time.sleep(0.05)
    return False


def _reload_candidate():
    """Non-exiting candidate config read for HOT RELOAD (T-191): returns the
    parsed+semantically-valid config, or None (keep last-good, warn once).
    Startup keeps the FATAL SystemExit policy via load_config()."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or engine_config.semantic_problems(
            data, "deathwatch_config.json"):
        return None
    return data


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

        digits_crop = _grab_safe(hwnd, cfg["timer_digits_region"])
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
            if not toggle_mouse_lock(hwnd):
                print("warning: mouse-lock toggle failed, mouse may remain locked")

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

        # T-202: wait until the game is REALLY the foreground window (and a
        # settle pause has passed) before any resurrect action - a click fired
        # while the switch is still landing can hit the window that was in
        # front a moment ago and pop its context menu over the game.
        if _wait_foreground(hwnd):
            if cfg.get("click_mid_on_resurrect"):
                mid = _mid_click_coords()
                if mid is None:
                    print("resurrect mid-click skipped: no validated mid coordinates")
                else:
                    x, y = mid
                    # T-178: verified inside the current client rect immediately
                    # before the click - an out-of-bounds coordinate never fires.
                    # click_at posts background messages straight into the game
                    # window, so the click can never land on another program.
                    if _client_bounds_ok(hwnd, x, y):
                        window_ctl.click_at(hwnd, x, y, button="left")
                        print(f"clicked mid on minimap ({x}, {y})")
                    else:
                        print(f"resurrect mid-click skipped: ({x}, {y}) outside client area")

            if cfg.get("lock_window_resurrect"):
                if not toggle_mouse_lock(hwnd):
                    print("warning: mouse-lock toggle failed after resurrect, mouse may remain locked")
        else:
            print("resurrect actions skipped: game did not become the foreground window")
    finally:
        _set_block(0)
        print("phase-3 finished, pedals unblocked")


def main(replace=False):
    engine_config.setup_logging()
    single_instance.ensure_single_instance("deathwatch", replace=replace)
    single_instance.start_parent_watchdog()
    window_ctl.set_dpi_aware()
    cfg_path = os.path.join(BASE, "deathwatch_config.json")
    # Guarded load FIRST (missing/corrupt -> deterministic FATAL, not a raw
    # getmtime traceback), then seed the mtime probe (T-082).
    cfg = load_config()
    key_blocker.start(cfg.get("blocked_keys", []))
    try:
        cfg_last_mtime = os.path.getmtime(cfg_path)
        hwnd = None
        loaded_window_title = cfg["window_title"]
        loaded_digits_dir = ""
        loaded_label_path = ""
        loaded_blocked_keys = list(cfg.get("blocked_keys", []))

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
                cfg_last_mtime, changed = engine_config.mtime_changed(cfg_path, cfg_last_mtime)
                if changed:
                    # T-155/T-191: hot reload is transactional as a WHOLE and
                    # NEVER kills the healthy running engine over one bad edit.
                    # A semantically-invalid revision is rejected (keep last-good,
                    # warn once); the mtime is consumed so the same revision does
                    # not re-trigger every poll.
                    candidate_cfg = _reload_candidate()
                    if candidate_cfg is None:
                        print("WARN: config change rejected (invalid); keeping last-good")
                        continue
                    reject = False
                    candidate_templates = None
                    if candidate_cfg["digit_templates_dir"] != loaded_digits_dir:
                        try:
                            candidate_templates = digit_reader.load_templates(
                                os.path.join(BASE, candidate_cfg["digit_templates_dir"]))
                        except OSError as e:
                            print("WARN: config change rejected: digit templates "
                                  "load failed (%s); keeping previous" % e)
                            reject = True
                        if not reject and not candidate_templates:
                            print("WARN: config change rejected: no usable digit "
                                  "templates in '%s'; keeping previous"
                                  % candidate_cfg["digit_templates_dir"])
                            reject = True
                    candidate_label = None
                    if not reject and candidate_cfg["death_label_template"] != loaded_label_path:
                        candidate_label = cv2.imread(
                            os.path.join(BASE, candidate_cfg["death_label_template"]),
                            cv2.IMREAD_GRAYSCALE)
                        if candidate_label is None:
                            print("WARN: config change rejected: death label template "
                                  "not found '%s'; keeping previous"
                                  % candidate_cfg["death_label_template"])
                            reject = True
                    if not reject:
                        cfg = candidate_cfg
                        if candidate_templates is not None:
                            templates = candidate_templates
                            loaded_digits_dir = candidate_cfg["digit_templates_dir"]
                            print("reloaded digit templates")
                        if candidate_label is not None:
                            label_template = candidate_label
                            loaded_label_path = candidate_cfg["death_label_template"]
                            print("reloaded death label template")

                if cfg["window_title"] != loaded_window_title:
                    loaded_window_title = cfg["window_title"]
                    hwnd = None
                    print(f"window title changed, now watching '{loaded_window_title}'")

                if cfg.get("blocked_keys", []) != loaded_blocked_keys:
                    key_blocker.stop()
                    key_blocker.start(cfg.get("blocked_keys", []))
                    loaded_blocked_keys = list(cfg.get("blocked_keys", []))
                    print(f"reloaded blocked keys: {loaded_blocked_keys}")

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

                label_crop = _grab_safe(hwnd, cfg["death_label_region"])
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
            except RuntimeError as e:
                # (T-154) Only capture/window failures are 'lost window' and
                # retryable. Anything else - a config bug, a resource problem,
                # a programming error - is FATAL: swallowing it here would loop
                # forever while pretending to be a transient window loss.
                print(f"lost window ({e}); will try to re-acquire...")
                was_dead = False
                hwnd = None
                time.sleep(1.0)
            except Exception as e:
                print(f"FATAL: unhandled deathwatch error ({type(e).__name__}: {e}); re-raising")
                raise
    finally:
        key_blocker.stop()


if __name__ == "__main__":
    import sys

    main(replace="--replace" in sys.argv)
