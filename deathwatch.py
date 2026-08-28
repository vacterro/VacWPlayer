import json
import os
import time

import cv2
import re
import win32gui

import capture
import config_store
import digit_reader
import engine_config
import key_blocker
import single_instance
import window_ctl
import ahk_builder

BASE = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE, "deathwatch_config.json")
DEATHWATCH_DEFAULTS = engine_config.canonical_default("deathwatch_config.json")


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


def _cursor_move_point(hwnd, cfg):
    """Screen point for the post-resurrect cursor move (T-204/T-CORE-011):
    the configured percent of the TARGET GAME CLIENT size (excluding borders
    and titlebar), converted to screen coords via GetClientRect + ClientToScreen.

    Returns None when the point would lie outside the client area or the
    hwnd is invalid."""
    try:
        # T-CORE-011: use GetClientRect (client area only, no borders/titlebar)
        # + ClientToScreen to convert to screen coordinates.
        left, top, right, bottom = win32gui.GetClientRect(hwnd)
        w = right - left
        h = bottom - top
        if w <= 0 or h <= 0:
            return None
        # Convert client (0,0) to screen coordinates for the offset.
        sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
        pct_x = cfg.get("cursor_move_x_pct", 75)
        pct_y = cfg.get("cursor_move_y_pct", 25)
        x = sx + int(pct_x * w / 100)
        y = sy + int(pct_y * h / 100)
        # Require the point lies inside the current client area.
        if not (sx <= x < sx + w and sy <= y < sy + h):
            return None
        return x, y
    except Exception:
        return None


def _move_cursor_tap(hwnd, x, y, hold_ms):
    """Move the PHYSICAL cursor to (x, y) and tap-hold LMB so the character
    starts walking there immediately (T-204).

    Real hardware input, so it is refused unless the game window is genuinely
    in the foreground IMMEDIATELY BEFORE the hardware DOWN (same guard as
    toggle_mouse_lock): a cursor grab fired while another window owns the
    screen would plant the click there.
    """
    import ctypes

    try:
        if not ctypes.windll.user32.SetCursorPos(x, y):
            return False
        # JIT foreground check immediately before hardware DOWN (T-CORE-007).
        if win32gui.GetForegroundWindow() != hwnd:
            print("cursor move skipped: game lost foreground between move and down")
            return False
        MOUSEEVENTF_LEFTDOWN = 0x02
        MOUSEEVENTF_LEFTUP = 0x04
        sent = []
        try:
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
            sent.append(MOUSEEVENTF_LEFTUP)
            time.sleep(max(0.0, hold_ms) / 1000.0)
            ctypes.windll.user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            sent.pop()
        finally:
            for ev in sent:
                ctypes.windll.user32.mouse_event(ev, 0, 0, 0, 0)
        return True
    except Exception as e:
        print(f"cursor move failed: {e}")
        return False


def _send_key_tap(hwnd, vk):
    """Real keydown+keyup of a virtual-key code (T-204). Refuses on None and
    JIT-checks foreground immediately before DOWN (T-CORE-007). Guarantees
    UP in finally after any successful DOWN (T-CORE-011)."""
    if not vk:
        return False
    import ctypes
    down_sent = False
    try:
        # JIT foreground check immediately before hardware DOWN.
        if win32gui.GetForegroundWindow() != hwnd:
            print("key tap skipped: game lost foreground before down")
            return False
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        down_sent = True
        time.sleep(0.05)
        return True
    except Exception as e:
        print(f"key tap failed: {e}")
        return False
    finally:
        # T-CORE-011: guarantee key-up in finally even if UP would raise.
        if down_sent:
            try:
                ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
            except Exception:
                pass


# T-CORE-012 / W2-003 / W2-004: process-shared runtime PvP-trigger state.
# Two mutually-exclusive sidecar files in BASE:
#   _RUNTIME_TRIGGER_PATH          -> an ACTIVE PvP combo was last applied; its
#                                     VK is published here.
#   _RUNTIME_TRIGGER_INACTIVE_PATH -> the user EXPLICITLY stopped (or applied a
#                                     config with no PvP combo); DeathWatch must
#                                     never fall back to config.json and re-arm
#                                     PvP. Presence of the file is the signal.
# W2-003: file-absence used to mean BOTH "first run (never applied)" and
# "explicitly stopped". Now an explicit stop persists the inactive marker so the
# two are distinguishable and _pvp_trigger_vk returns None when inactive.
# W2-004: publication is strict - _write_runtime_trigger returns True only on a
# fully-published state and tears everything down (no stale sidecar survives) on
# any failure, instead of swallowing the error and leaving an old file behind.
_RUNTIME_TRIGGER_PATH = os.path.join(BASE, ".runtime_pvp_trigger")
_RUNTIME_TRIGGER_INACTIVE_PATH = os.path.join(BASE, ".runtime_pvp_trigger_inactive")


def _remove_if_present(path):
    """Remove a file if present. Returns True when removed, False when absent.
    Raises OSError on real deletion failure (e.g. permission denied, file
    locked) so the caller can distinguish absent from failure (CORE-005)."""
    try:
        os.remove(path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        raise


def _write_runtime_trigger(config_data):
    """Publish the accepted PvP trigger state to a process-shared sidecar after a
    successful AHK Apply (T-CORE-012). Returns True only when the state is fully
    published; False (after tearing down any partial/stale sidecar) on failure
    (W2-004), so the caller can fail safe instead of trusting a stale trigger.

    Publishes exactly one of two states:
      * active  : a PvP combo exists with a sendable trigger VK -> write the VK
                  to _RUNTIME_TRIGGER_PATH and delete the inactive marker.
      * inactive: no PvP combo (or no sendable VK) -> remove the active file and
                  write _RUNTIME_TRIGGER_INACTIVE_PATH so DeathWatch never
                  re-arms PvP from config.json after an explicit stop (W2-003).
    """
    try:
        combos, _ = ahk_builder._active_combos(config_data)
    except Exception:
        # Cannot determine state -> fail safe: wipe any sidecar, report failure.
        _clear_runtime_trigger()
        return False
    pvp = next((c for c in combos if c.get("tag", "").endswith("_pvp")), None)
    if pvp is None:
        return _set_runtime_inactive()
    trig_list = pvp.get("triggers") or [pvp.get("trigger", "")]
    trig = trig_list[0]
    vk = _trigger_vk(trig)
    if vk is None:
        # A PvP combo exists but its trigger is not keybd_event-sendable, so the
        # restart can never fire - record an explicit inactive state.
        return _set_runtime_inactive()
    try:
        tmp = _RUNTIME_TRIGGER_PATH + ".tmp"
        with open(tmp, "w") as f:
            f.write(str(vk))
        os.replace(tmp, _RUNTIME_TRIGGER_PATH)
    except OSError:
        # Active write failed: ensure an authoritative inactive sidecar so the
        # reader returns None, never a stale partial state (CORE-005).
        _remove_if_present(_RUNTIME_TRIGGER_PATH)
        try:
            _publish_inactive_file()
        except OSError:
            pass
        return False
    # Active published; require successful removal of inactive before reporting
    # True. A deletion failure here is a real cross-state ambiguity and must
    # not be reported as success (CORE-005).
    try:
        _remove_if_present(_RUNTIME_TRIGGER_INACTIVE_PATH)
    except OSError:
        return False
    return True


def _publish_inactive_file():
    """Write the inactive marker atomically. Raises OSError on real failure.
    CORE-005: callers must publish inactive FIRST so the reader is fail-safe
    even if a subsequent active remove fails."""
    tmp = _RUNTIME_TRIGGER_INACTIVE_PATH + ".tmp"
    with open(tmp, "w") as f:
        f.write("")
    os.replace(tmp, _RUNTIME_TRIGGER_INACTIVE_PATH)


def _set_runtime_inactive():
    """Persist an explicit 'PvP is inactive' sidecar (W2-003). DeathWatch checks
    this BEFORE any config.json fallback, so an explicit Stop (or an Apply with no
    PvP combo) is never silently overridden by a config PvP combo. Returns True on
    success, False and a full teardown on failure (W2-004). CORE-005: inactive
    is published FIRST so the reader is fail-safe even if a subsequent stale
    active remove fails."""
    try:
        _publish_inactive_file()
    except OSError:
        _remove_if_present(_RUNTIME_TRIGGER_INACTIVE_PATH)
        return False
    # Inactive now authoritative; best-effort cleanup of stale active. A
    # failure here is not a hard error - the reader still resolves to None.
    try:
        _remove_if_present(_RUNTIME_TRIGGER_PATH)
    except OSError:
        pass
    return True


def _clear_runtime_trigger():
    """Hard wipe of ALL runtime-trigger sidecar state (T-CORE-012)."""
    _remove_if_present(_RUNTIME_TRIGGER_PATH)
    _remove_if_present(_RUNTIME_TRIGGER_INACTIVE_PATH)


def _pvp_trigger_vk():
    """Virtual-key code of the active PvP combo's first trigger (T-204).

    W2-003: an explicit-inactive sidecar (written on Stop / no-PvP Apply) takes
    precedence and returns None, so DeathWatch never re-arms PvP from config.json
    after the user stopped. Otherwise prefer the process-shared runtime trigger
    file written by the GUI after a successful AHK Apply; fall back to config.json
    only when that file is absent (first run before any Apply).
    """
    # W2-003: explicit inactive state wins over everything.
    if os.path.exists(_RUNTIME_TRIGGER_INACTIVE_PATH):
        return None
    # Prefer the process-shared runtime trigger file (accepted last-applied).
    try:
        with open(_RUNTIME_TRIGGER_PATH) as f:
            vk = int(f.read().strip())
        if 0 < vk < 0x10000:
            return vk
    except (OSError, ValueError):
        pass
    # Fallback: derive from the EFFECTIVE config - stable config.json merged
    # with the volatile config.local.json (champion enabled_/toggle_ flags),
    # exactly as the GUI loads it. The stable half intentionally omits those
    # flags, so reading it alone would re-enable a PvP slot disabled in local
    # (CORE-015). Malformed/unreadable local state fails closed.
    try:
        with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or config_store.validate_config(data):
        return None
    try:
        with open(os.path.join(BASE, "config.local.json"), encoding="utf-8") as f:
            local = json.load(f)
    except (OSError, ValueError):
        local = {}
    if config_store.validate_local_config(local):
        return None  # CORE-015: malformed local -> fail closed, never default-True
    if isinstance(local, dict) and local:
        data = config_store.merge_volatile(data, local)
    try:
        combos, _ = ahk_builder._active_combos(data)
    except Exception:
        return None
    pvp = next((c for c in combos if c.get("tag", "").endswith("_pvp")), None)
    if pvp is None:
        return None
    trig = (pvp.get("triggers") or [pvp.get("trigger", "")])[0]
    return _trigger_vk(trig)


def _trigger_vk(trig):
    """Map a combo trigger token to a virtual-key code (T-204): single ASCII
    letter/digit (via the canonical parser), F1-F24, MButton, or vkNN hex.
    None for anything the keybd_event-based restart cannot send."""
    if not isinstance(trig, str) or not trig:
        return None
    vk = window_ctl.key_vk(trig)
    if vk is not None:
        return vk
    t = trig.strip().lower()
    if re.fullmatch(r"f([1-9]|1\d|2[0-4])", t):
        return 0x70 + int(t[1:]) - 1
    if t in ("mbutton", "rbutton", "lbutton"):
        return {"mbutton": 0x04, "rbutton": 0x02, "lbutton": 0x01}[t]
    if re.fullmatch(r"vk[0-9a-f]{1,4}", t):
        return int(t[2:], 16)
    return None


def _wait_foreground(hwnd, timeout=3.0, settle=0.2):
    """Wait until `hwnd` is genuinely the foreground window, then settle.

    SetForegroundWindow can win the race ahead of the window's input routing
    actually switching (T-202): an action fired the instant the check passes
    can still land in whatever was in front a moment before. Polling until the
    foreground check holds, plus a settle pause, makes every resurrect action
    land inside the game window. False = never became foreground (or a probe
    failed) - callers must skip, never force.

    PERF-005: uses time.monotonic() for the timeout so Windows clock
    adjustments cannot shorten/extend the wait.
    """
    t_end = time.monotonic() + timeout
    while time.monotonic() < t_end:
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


def handle_death(hwnd, cfg, templates, hwnd_title="", hwnd_pid=0):
    """Death event handler (CORE-007: carries expected title+PID identity so
    post-wait actions can revalidate the HWND against the original target -
    a reused numeric handle after a long respawn wait must never be treated as
    the game window."""
    print("death detected")

    pedal_block_sec = cfg.get("pedal_block_sec", DEATHWATCH_DEFAULTS["pedal_block_sec"])
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
        work_title = None
        work_pid = 0
        if cfg.get("switch_to_work_window") and cfg.get("work_window_title"):
            try:
                # W2-009: bind the work window to title+PID identity so a reused
                # HWND after the respawn wait is never minimized.
                work_hwnd, work_pid = capture.find_window_identity(
                    cfg["work_window_title"])
                work_title = cfg["work_window_title"]
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
        # W2-009: revalidate the work window identity before touching it.
        if work_title and capture.is_same_window(work_hwnd, work_title, work_pid):
            window_ctl.switch_to(work_hwnd)
            print(f"switched to work window '{cfg['work_window_title']}'")
        else:
            print(f"work window '{cfg['work_window_title']}' changed identity, skipping switch")
            work_hwnd = None
        
    print(f"waiting {wait:.1f}s, spilling pedals suppressed")
    if wants_block:
        key_blocker.block_until_released()
        
    user_aborted = False
    # PERF-005: use time.monotonic() for relative durations so Windows
    # clock adjustments (NTP, manual) cannot shorten/extend waits.
    t_end = time.monotonic() + wait
    settle_time = time.monotonic() + 2.0
    while time.monotonic() < t_end:
        time.sleep(1.0)
        if time.monotonic() > settle_time and not win32gui.IsIconic(hwnd) and win32gui.GetForegroundWindow() == hwnd:
            print("user manually focused game, aborting automation")
            user_aborted = True
            break
            
    if user_aborted:
        _set_block(0)
        return
        
    if work_hwnd:
        # W2-009: revalidate identity again before the post-wait minimize - the
        # work window may have closed and had its HWND reused during the wait.
        if work_title and capture.is_same_window(work_hwnd, work_title, work_pid):
            window_ctl.minimize(work_hwnd)
        else:
            print(f"work window '{cfg['work_window_title']}' changed identity, skipping minimize")

    # === PHASE 3: Block during restore to catch pedal spam ===
    _set_block(pedal_block_sec if wants_block else 0)

    # PHASE 3 try/finally: separate guard so a failure in
    # maximize_and_focus or resurrect actions never leaks the block.
    try:
        # CORE-007: the target may have closed and had its numeric HWND reused
        # during the long respawn wait. Revalidate title+PID identity before any
        # restore/focus/click/cursor action; a mismatch/UNKNOWN aborts the death
        # event without delivering input to an unrelated window.
        if hwnd_pid and not capture.is_same_window(hwnd, hwnd_title, hwnd_pid):
            print("game window identity changed during wait - aborting resurrect actions")
            return
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

            if cfg.get("cursor_move_on_resurrect"):
                # T-204: move the physical cursor to the configured 1/4-screen
                # point (default top-right) and tap-hold LMB, so the champion
                # starts walking there the moment the game is back.
                point = _cursor_move_point(hwnd, cfg)
                if point is None:
                    print("cursor move skipped: could not compute valid point")
                else:
                    cx, cy = point
                    if _move_cursor_tap(hwnd, cx, cy, cfg.get("cursor_move_hold_ms", 250)):
                        print(f"cursor moved to ({cx}, {cy}) and tapped for movement")
                    else:
                        print(f"cursor move to ({cx}, {cy}) skipped")

            if cfg.get("pvp_after_resurrect"):
                # T-204: start the PvP combo right after resurrect by sending
                # its trigger key - the runtime hotkey arms the combo spam.
                vk = _pvp_trigger_vk()
                if vk is None:
                    print("pvp restart skipped: no validated pvp combo trigger")
                elif _send_key_tap(hwnd, vk):
                    print(f"pvp combo started after resurrect (vk={vk:#04x})")
                else:
                    print("pvp restart failed: trigger key could not be sent")

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
    cfg_path = os.path.join(BASE, "deathwatch_config.json")
    # T-W2-001: validate config and resources BEFORE acquiring the single-instance
    # mutex so a bad candidate cannot destructively replace a healthy running engine.
    try:
        cfg, candidate_revision = engine_config.load_config_revision(
            cfg_path, "deathwatch_config.json")
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(1)
    try:
        templates = digit_reader.load_templates(os.path.join(BASE, cfg["digit_templates_dir"]))
        if not templates:
            print("FATAL: no usable digit templates in '%s' - not starting" % cfg["digit_templates_dir"])
            raise SystemExit(1)
    except Exception:
        print("FATAL: failed to load digit templates - not starting")
        raise SystemExit(1)
    label_template = cv2.imread(os.path.join(BASE, cfg["death_label_template"]), cv2.IMREAD_GRAYSCALE)
    if label_template is None:
        print("FATAL: death label template not found: %s" % cfg["death_label_template"])
        raise SystemExit(1)
    # Candidate ready: acquire ownership and start runtime side effects.
    # W2-004/CORE-006: candidate_revision is already bound to the bytes parsed
    # above (load_config_revision pins it to the open handle), so the reload
    # tracker seeds from the validated file state, not a fresh post-replacement
    # stat.
    single_instance.ensure_single_instance("deathwatch", replace=replace)
    single_instance.start_parent_watchdog()
    window_ctl.set_dpi_aware()
    # T-W2-PERF-007: the 1ms timer resolution is NO LONGER requested for the
    # process lifetime here. It is scoped to the short quick-buy input burst via
    # window_ctl.press_key_burst's timer_resolution() context manager, so the
    # whole system is not pinned to a 1ms quantum just because DeathWatch started.
    key_blocker.start(cfg.get("blocked_keys", DEATHWATCH_DEFAULTS["blocked_keys"]))
    try:
        # W2-004: initialise from the candidate's proven revision token.
        cfg_last_revision = (candidate_revision
                             if candidate_revision
                             else engine_config.config_revision(cfg_path))
        hwnd = None
        hwnd_title = None
        hwnd_pid = 0
        loaded_window_title = cfg["window_title"]
        loaded_digits_dir = cfg["digit_templates_dir"]
        loaded_label_path = cfg["death_label_template"]
        loaded_blocked_keys = list(cfg.get("blocked_keys", DEATHWATCH_DEFAULTS["blocked_keys"]))

        was_dead = False
        print(f"watching for window '{loaded_window_title}'...")
        print(f"watching hwnd={hwnd}, ctrl+c to stop")
        while True:
            try:
                cfg_last_revision, changed = engine_config.mtime_changed(cfg_path, cfg_last_revision)
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
                        except (OSError, ValueError, cv2.error) as e:
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

                if cfg.get("blocked_keys", DEATHWATCH_DEFAULTS["blocked_keys"]) != loaded_blocked_keys:
                    # PERF-005: update the live hook in place - no stop()/start()
                    # teardown, so there is never a gap where blocking is off.
                    key_blocker.update_keys(cfg.get("blocked_keys", DEATHWATCH_DEFAULTS["blocked_keys"]))
                    loaded_blocked_keys = list(cfg.get("blocked_keys", DEATHWATCH_DEFAULTS["blocked_keys"]))
                    print(f"reloaded blocked keys: {loaded_blocked_keys}")

                # W2-002: bind the handle to the target's title + owning PID so a
                # handle reclaimed by a foreign window (which still passes
                # IsWindow) is detected and re-acquired instead of being watched.
                if not capture.is_same_window(hwnd, hwnd_title, hwnd_pid):
                    hwnd = None
                if not hwnd:
                    try:
                        hwnd, hwnd_pid = capture.find_window_identity(
                            cfg["window_title"])
                        hwnd_title = cfg["window_title"]
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
                    handle_death(hwnd, cfg, templates, hwnd_title, hwnd_pid)
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
