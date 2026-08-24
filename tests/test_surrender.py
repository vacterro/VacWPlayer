"""CORE-007: surrender usability must be config/mode-aware at startup AND on
every reload. A metadata-only reload that flips mode to one whose targets no
longer match must be rejected (keep last-good), never silently committed as a
permanent no-op."""

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import poller_engine
import surrender


def _t(action):
    return [{"name": action, "action": action, "file": "x.png",
             "threshold": 0.75, "region": [0, 0, 1, 1]}]


def test_usable_with_cfg_accept_mode():
    cfg = {"auto_accept": True}
    assert surrender._targets_usable_with_cfg(_t("accept"), cfg) is True
    assert surrender._targets_usable_with_cfg(_t("decline"), cfg) is False


def test_usable_with_cfg_decline_mode():
    cfg = {"auto_accept": False}
    assert surrender._targets_usable_with_cfg(_t("decline"), cfg) is True
    assert surrender._targets_usable_with_cfg(_t("accept"), cfg) is False


def test_usable_with_cfg_defaults_accept():
    # No auto_accept key defaults to accept mode.
    assert surrender._targets_usable_with_cfg(_t("accept"), {}) is True
    assert surrender._targets_usable_with_cfg(_t("decline"), {}) is False


def test_usable_with_cfg_empty():
    assert surrender._targets_usable_with_cfg([], {"auto_accept": True}) is False


# --- CORE-008: legacy surrender action migration is real at the load boundary ---
import json as _json
import tempfile
import os as _os


def _legacy_surrender_cfg():
    return {
        "window_title": "W",
        "auto_accept": False,
        "templates": [
            {"name": "Accept", "file": "a.png", "threshold": 0.75},
            {"name": "Decline", "file": "d.png", "threshold": 0.75},
        ],
    }


def test_normalize_attaches_action():
    import engine_config
    cfg = _legacy_surrender_cfg()
    out = engine_config.normalize_surrender_actions(_json.loads(_json.dumps(cfg)),
                                                    "surrender_config.json")
    assert out["templates"][0]["action"] == "accept"
    assert out["templates"][1]["action"] == "decline"


def test_normalize_ignores_other_engines():
    import engine_config
    cfg = _legacy_surrender_cfg()
    # A non-surrender engine must not be mutated.
    out = engine_config.normalize_surrender_actions(_json.loads(_json.dumps(cfg)),
                                                    "accept_config.json")
    assert "action" not in out["templates"][0]


def test_validate_engine_config_returns_normalized_surrender():
    import engine_config
    cfg = _legacy_surrender_cfg()
    out = engine_config.validate_engine_config(_json.loads(_json.dumps(cfg)),
                                               "surrender_config.json")
    # The returned config carries the migrated actions (CORE-008) so the engine
    # can actually match targets - not just pass validation silently.
    assert out["templates"][0]["action"] == "accept"
    assert out["templates"][1]["action"] == "decline"


def test_ambiguous_name_still_flagged():
    import engine_config
    cfg = {
        "window_title": "W",
        "templates": [{"name": "auto_accept", "file": "a.png", "threshold": 0.75}],
    }
    problems = engine_config.semantic_problems(cfg, "surrender_config.json")
    assert any("ambiguous" in p for p in problems)
    with pytest.raises(SystemExit):
        engine_config.validate_engine_config(cfg, "surrender_config.json")


def test_reload_candidate_returns_normalized(tmp_path):
    # Hot reload (reload_candidate) must also return the normalized config, not
    # the raw legacy one, so a reload doesn't silently drop every target.
    import poller_engine
    path = tmp_path / "surrender_config.json"
    path.write_text(_json.dumps(_legacy_surrender_cfg()))
    out, err = poller_engine.reload_candidate(str(path), "surrender_config.json")
    assert err is None
    assert out["templates"][0]["action"] == "accept"
    assert out["templates"][1]["action"] == "decline"


class _SleepSentinel:
    def __init__(self, stop_after):
        self.stop_after = stop_after
        self.calls = 0

    def __call__(self, secs):
        self.calls += 1
        if self.calls >= self.stop_after:
            raise KeyboardInterrupt


def _run_poller_mode_mismatch(monkeypatch, start_cfg, reload_cfg, start_targets,
                              stop_after=3):
    def _build(c):
        return [dict(t) for t in start_targets]

    def _mode_usable(targets, cfg):
        targets = targets or []
        action = "accept" if cfg.get("auto_accept", True) else "decline"
        return bool([e for e in targets if e.get("action") == action])

    state = {"calls": 0}

    def _changed(p, m):
        state["calls"] += 1
        return ((2, 2), state["calls"] == 1)

    def _reload(p, n):
        return (reload_cfg, None)

    monkeypatch.setattr(poller_engine.engine_config, "load_config_revision",
                        lambda p, n: (start_cfg, (1, 1)))
    monkeypatch.setattr(poller_engine, "reload_candidate", _reload)
    monkeypatch.setattr(poller_engine.engine_config, "mtime_changed", _changed)
    monkeypatch.setattr(poller_engine.time, "sleep", _SleepSentinel(stop_after))
    monkeypatch.setattr(poller_engine.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(poller_engine.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(poller_engine.window_ctl, "set_dpi_aware", lambda: None)
    monkeypatch.setattr(poller_engine.capture, "find_window", lambda t: 12345)
    monkeypatch.setattr(poller_engine.win32gui, "IsWindow", lambda h: True)
    monkeypatch.setattr(poller_engine.capture, "is_minimized", lambda h: False)

    poller_engine.run_poller(
        "surrender", "cfg.json", "cfg.json",
        build_targets=_build,
        scan_targets=lambda h, c, t: False,
        startup=lambda c, t: "started",
        reload_msg=lambda c, t: None,
        usable=_mode_usable)


def test_startup_mode_mismatch_is_fatal(monkeypatch):
    # auto_accept=False (mode=decline) with only accept targets -> not usable at
    # startup -> deterministic FATAL, never a silent no-op engine.
    cfg = {"window_title": "W", "auto_accept": False}
    targets = _t("accept")

    def _build(c):
        return list(targets)

    def _mode_usable(targets, cfg):
        targets = targets or []
        action = "accept" if cfg.get("auto_accept", True) else "decline"
        return bool([e for e in targets if e.get("action") == action])

    monkeypatch.setattr(poller_engine.engine_config, "load_config_revision",
                        lambda p, n: (cfg, (1, 1)))
    monkeypatch.setattr(poller_engine.single_instance, "ensure_single_instance",
                        lambda *a, **k: None)
    monkeypatch.setattr(poller_engine.single_instance, "start_parent_watchdog",
                        lambda: None)
    monkeypatch.setattr(poller_engine.window_ctl, "set_dpi_aware", lambda: None)

    with pytest.raises(SystemExit) as ex:
        poller_engine.run_poller(
            "surrender", "cfg.json", "cfg.json",
            build_targets=_build, scan_targets=lambda h, c, t: False,
            startup=lambda c, t: "started", reload_msg=lambda c, t: None,
            usable=_mode_usable)
    assert ex.value.code == 1


def test_reload_mode_mismatch_keeps_last_good(monkeypatch, capsys):
    # CORE-007: metadata-only reload (same targets, auto_accept True->False)
    # would leave a decline-mode engine with only accept targets - a silent
    # permanent no-op. run_poller must reject it and keep last-good.
    start_cfg = {"window_title": "W", "auto_accept": True}
    reload_cfg = {"window_title": "W", "auto_accept": False}
    start_targets = _t("accept")

    _run_poller_mode_mismatch(monkeypatch, start_cfg, reload_cfg, start_targets)

    out = capsys.readouterr().out
    assert "no usable targets" in out
    assert "keeping last-good" in out


def test_reload_mode_match_commits(monkeypatch, capsys):
    # A mode flip to one whose targets DO match is committed normally.
    start_cfg = {"window_title": "W", "auto_accept": True}
    reload_cfg = {"window_title": "W", "auto_accept": False}
    # Both accept and decline targets present: decline mode is usable too.
    start_targets = _t("accept") + _t("decline")

    _run_poller_mode_mismatch(monkeypatch, start_cfg, reload_cfg, start_targets)

    out = capsys.readouterr().out
    assert "no usable targets" not in out
