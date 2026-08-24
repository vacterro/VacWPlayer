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
import win32gui  # re-exported for tests that monkeypatch poller_engine.win32gui

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


def reload_candidate(config_path, config_name):
    """Non-exiting candidate load for HOT RELOAD (T-191).

    Startup keeps the FATAL policy (load_config); a hot reload must NEVER kill
    a healthy running engine over one bad edit. Returns (cfg, None) or
    (None, diagnostic) - the caller keeps the last-good cfg and warns once
    (the changed mtime is already consumed, so the same revision does not
    re-trigger every poll)."""
    try:
        with open(config_path) as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        return None, "unreadable: %s" % e
    problems = engine_config.semantic_problems(data, config_name)
    if problems:
        return None, "; ".join(problems[:2])
    # CORE-008: hot reload returns the NORMALIZED config (legacy Accept/Decline
    # template names get an explicit `action`) so the running engine's targets
    # carry actions - otherwise a reload of a legacy config would silently drop
    # all targets and idle as a no-op.
    return engine_config.normalize_surrender_actions(data, config_name), None


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
            # Clamp to >=1: a 1x1 template scaled down computes 0 and
            # cv2.resize(0,0) raises (T-091). Normal-size behavior unchanged.
            scaled_templates.append(cv2.resize(
                tmpl, (max(1, int(w * scale)), max(1, int(h * scale)))))
        loaded.append({
            "name": entry.get("name", "?"),
            "templates": scaled_templates,
            "threshold": float(entry.get("threshold", 0.75)),
        })
        # W2-003: preserve action field through the config->runtime boundary
        # so surrender's mode-aware _scan can filter by configured action.
        if "action" in entry:
            loaded[-1]["action"] = entry["action"]
        if entry.get("region") is not None:
            loaded[-1]["region"] = entry["region"]
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


def click_template_match(hwnd, gray, entry, origin=(0, 0)):
    """Click the best matching scaled-template location in a full-window gray image.

    `origin` offsets the click coordinates - used when `gray` is a crop of a
    larger capture, so the click lands in window space, not crop space.
    """
    score, loc, size = best_template_match(gray, entry)
    # loc/size are None only when no template matched at all - a real match at
    # the top-left corner is (0, 0), which must NOT be treated as falsy (T-083).
    if score < entry["threshold"] or loc is None or size is None:
        return False
    th, tw = size
    cx, cy = loc[0] + tw // 2 + origin[0], loc[1] + th // 2 + origin[1]
    print("matched '%s' (score=%.2f), clicking (%d,%d)" % (entry["name"], score, cx, cy))
    window_ctl.click_at(hwnd, cx, cy, button="left")
    return True


def has_regions(entries):
    """True when every entry carries a `region` - the cheap-region scan applies."""
    return bool(entries) and all(e.get("region") is not None for e in entries)


def scan_by_region(hwnd, entries, match=click_template_match):
    """Region-only scan: one grab for the union box, per-entry crop.

    Far lighter than the full-window grab: grab_region BitBlt's only the
    pixels the buttons actually occupy, instead of PrintWindow's entire-surface
    re-render, so a fast poll interval stops showing up on a CPU graph and in
    the emulator's frame pacing. Returns True (clicked), False (no match) or
    None (transient capture failure), matching scan_targets' contract.

    Occlusion policy (T-146): the cheap BitBlt path only runs while the
    window is foreground - the only state where the screen pixels provably
    belong to it. With the window occluded or in the background (the
    accept/surrender contract), it falls back to PrintWindow + crop
    (grab_client_region) so the engine never matches - let alone clicks -
    foreign pixels.

    W2-008: rejects entries whose region is not wholly inside the current
    client area before any BitBlt/crop/match.
    """
    # W2-008: filter out-of-client entries before computing the union box.
    try:
        cw, ch = capture.get_client_size(hwnd)
    except Exception:
        # CORE-009: UNKNOWN client geometry is NOT safe - never substitute
        # fabricated bounds that would admit out-of-client regions.
        return None
    valid = [e for e in entries
             if (0 <= e["region"][0] < e["region"][2] <= cw
                 and 0 <= e["region"][1] < e["region"][3] <= ch)]
    if not valid:
        return False
    x0 = min(e["region"][0] for e in valid)
    y0 = min(e["region"][1] for e in valid)
    x1 = max(e["region"][2] for e in valid)
    y1 = max(e["region"][3] for e in valid)
    try:
        if capture.is_foreground(hwnd):
            img = capture.grab_region(hwnd, (x0, y0, x1, y1))
        else:
            img = capture.grab_client_region(hwnd, (x0, y0, x1, y1))
    except RuntimeError:
        return None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    for entry in valid:
        r = entry["region"]
        crop = gray[r[1] - y0:r[3] - y0, r[0] - x0:r[2] - x0]
        if crop.shape[0] < 1 or crop.shape[1] < 1:
            continue
        if match(hwnd, crop, entry, origin=(r[0], r[1])):
            return True
    return False


def _target_signature(cfg):
    """PERF-003: immutable fingerprint of the fields consumed by build_targets.
    Used to skip expensive resource rebuilds when only metadata changed.
    Callers supply their own implementation via the target_sig parameter."""
    import hashlib
    # Include template-relevant fields only; metadata fields like
    # poll_interval_sec, click_cooldown_sec, window_title are excluded.
    templates = cfg.get("templates", [])
    buttons = cfg.get("buttons", [])
    sig_data = json.dumps({"templates": templates, "buttons": buttons},
                          sort_keys=True, default=str)
    return hashlib.sha256(sig_data.encode()).hexdigest()


def run_poller(name, config_path, config_name, build_targets, scan_targets,
               startup, reload_msg, poll_default=1.0, cooldown_default=3.0,
               replace=False, usable=None, target_sig=None):
    """Run the shared poll loop. scan_targets returns True (clicked), False (no
    match) or None (transient capture failure - retry after the poll interval).

    `usable(targets, cfg)` is an optional safety gate (T-138): when provided, a
    target set it rejects is never committed. At startup a rejected set is a
    deterministic FATAL (SystemExit 1) - an engine with zero usable targets
    must not idle forever. On hot reload a rejected set keeps the last-good
    config and targets transactionally, warning once instead of losing work.
    The predicate receives the CANDIDATE cfg so it can gate mode-aware usability
    (e.g. surrender declining-only when auto_accept is off) against the config
    the candidate would actually run (CORE-007).

    T-W2-001: validate config and resources BEFORE acquiring the single-instance
    mutex so a bad candidate cannot destructively replace a healthy running engine.
    """
    engine_config.setup_logging()

    # Candidate readiness check FIRST: validate config, build targets, verify
    # usability - only then acquire the mutex so we never kill a healthy holder
    # over a bad candidate (T-W2-001).
    try:
        cfg, candidate_revision = engine_config.load_config_revision(
            config_path, config_name)
    except SystemExit:
        raise
    except Exception:
        raise SystemExit(1)
    try:
        targets = build_targets(cfg)
    except Exception:
        print("FATAL: failed to build targets for %s - not starting" % config_name)
        raise SystemExit(1)
    if usable is not None and not usable(targets, cfg):
        print("FATAL: no usable targets in %s - not starting" % config_name)
        raise SystemExit(1)

    # W2-004/CORE-006: candidate_revision is already bound to the exact bytes
    # parsed above (load_config_revision pins it to the open file handle), so the
    # reload tracker seeds from the file state we validated - not a fresh stat
    # taken after a possible concurrent rewrite.

    # Candidate is ready: now acquire ownership and start runtime side effects.
    single_instance.ensure_single_instance(name, replace=replace)
    single_instance.start_parent_watchdog()
    window_ctl.set_dpi_aware()

    # W2-004: initialise from the candidate's proven revision token.
    cfg_last_revision = (candidate_revision
                         if candidate_revision
                         else engine_config.config_revision(config_path))
    hwnd = None
    hwnd_title = None
    hwnd_pid = 0
    loaded_window_title = cfg["window_title"]
    print(startup(cfg, targets))

    while True:
        try:
            cfg_last_revision, changed = engine_config.mtime_changed(
                config_path, cfg_last_revision)
            if changed:
                # T-191: a hot reload that cannot validate is REJECTED whole
                # (keep last-good, warn once) - never a SystemExit that kills
                # the healthy running engine over one bad edit.
                new_cfg, reload_err = reload_candidate(config_path, config_name)
                if new_cfg is None:
                    print("WARN: config change rejected: %s; "
                          "keeping last-good" % reload_err)
                else:
                    # PERF-003: skip expensive resource rebuild when only
                    # metadata (poll_interval, cooldown, window_title) changed;
                    # the new config is committed in either branch below.
                    _sig_fn = target_sig or _target_signature
                    if (_sig_fn(new_cfg) == _sig_fn(cfg)):
                        # PERF-003: target-defining fields unchanged - but
                        # CORE-007: still gate usability against the CANDIDATE
                        # config, because a metadata-only reload can flip mode
                        # (e.g. auto_accept) to one whose targets no longer
                        # match, which would silently commit a permanent no-op.
                        if usable is not None and not usable(targets, new_cfg):
                            print("config change ignored: no usable targets in %s; "
                                  "keeping last-good config" % config_name)
                        else:
                            cfg = new_cfg
                    else:
                        # W2-005: catch expected resource/OpenCV build failures
                        # around hot-reload so a corrupt template or resource
                        # error never kills a healthy last-good engine.
                        try:
                            new_targets = build_targets(new_cfg)
                        except (OSError, ValueError, cv2.error) as e:
                            print("WARN: config change rejected: resource build "
                                  "failed (%s); keeping last-good" % e)
                            continue
                        if usable is not None and not usable(new_targets, new_cfg):
                            print("config change ignored: no usable targets in %s; "
                                  "keeping last-good config" % config_name)
                        else:
                            cfg = new_cfg
                            targets = new_targets

                    # CORE-005: a window-title change must invalidate the
                    # captured hwnd unconditionally - a metadata-only reload
                    # (identical targets, new title) previously kept polling
                    # the now-stale handle because this check lived inside the
                    # rebuild branch and never ran for the signature-skip path.
                    if cfg["window_title"] != loaded_window_title:
                        loaded_window_title = cfg["window_title"]
                        hwnd = None
                        print("window title changed, now watching '%s'" % loaded_window_title)
                    msg = reload_msg(cfg, targets)
                    if msg:
                        print(msg)

            # W2-002: bind the handle to the target's title + owning PID. IsWindow
            # alone is insufficient - a destroyed target whose numeric handle is
            # reclaimed by a foreign window still passes IsWindow and would
            # otherwise be scanned/clicked. A title or PID mismatch means the
            # handle was reused; drop it and re-acquire.
            if not capture.is_same_window(hwnd, hwnd_title, hwnd_pid):
                hwnd = None
            if not hwnd:
                try:
                    hwnd, hwnd_pid = capture.find_window_identity(
                        cfg["window_title"])
                    hwnd_title = cfg["window_title"]
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
        except RuntimeError as e:
            print("lost window (%s); will try to re-acquire..." % e)
            hwnd = None
            time.sleep(1.0)
        except Exception as e:
            # (T-149-B) Only window/capture failures are 'lost window' and are
            # retryable. Anything else - a config bug, a bad template, a
            # programming error - is FATAL: swallowing it here would loop
            # forever while pretending to be a transient window loss.
            print("FATAL: unhandled poll error (%s: %s); re-raising"
                  % (type(e).__name__, e))
            raise

