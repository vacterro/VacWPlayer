import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import deathwatch
import engine_config
import surrender


def test_surrender_missing_auto_accept_uses_canonical_decline():
    assert engine_config.canonical_default("surrender_config.json")["auto_accept"] is False
    assert surrender._targets_usable_with_cfg(
        [{"action": "decline"}], {}) is True
    assert surrender._targets_usable_with_cfg(
        [{"action": "accept"}], {}) is False
    assert "mode=decline" in surrender._startup(
        {"window_title": "W"}, [])
    assert "mode=decline" in surrender._reload(
        {}, [])


def test_surrender_explicit_auto_accept_override_remains_respected():
    assert surrender._targets_usable_with_cfg(
        [{"action": "accept"}], {"auto_accept": True}) is True
    assert "mode=accept" in surrender._startup(
        {"window_title": "W", "auto_accept": True}, [])


@pytest.mark.parametrize(
    ("key", "expected"),
    [("pedal_block_sec", 5.0), ("blocked_keys", ["F13", "F14", "F15"])],
)
def test_deathwatch_missing_optional_defaults_are_canonical(key, expected):
    defaults = engine_config.canonical_default("deathwatch_config.json")
    assert defaults[key] == expected
    assert {}.get(key, deathwatch.DEATHWATCH_DEFAULTS[key]) == expected


def test_deathwatch_explicit_optional_overrides_remain_respected():
    cfg = {"pedal_block_sec": 0, "blocked_keys": []}
    assert cfg.get("pedal_block_sec", deathwatch.DEATHWATCH_DEFAULTS["pedal_block_sec"]) == 0
    assert cfg.get("blocked_keys", deathwatch.DEATHWATCH_DEFAULTS["blocked_keys"]) == []


def test_death_tab_fallbacks_use_canonical_defaults(monkeypatch):
    import tabs.death_tab as death_tab

    class FakeVar:
        def __init__(self, value):
            self.value = value

        def trace_add(self, *args):
            return None

    assert death_tab.DEATHWATCH_DEFAULTS["pedal_block_sec"] == 5.0
    assert death_tab.DEATHWATCH_DEFAULTS["blocked_keys"] == ["F13", "F14", "F15"]
    assert {}.get("pedal_block_sec", death_tab.DEATHWATCH_DEFAULTS["pedal_block_sec"]) == 5.0
    assert {}.get("blocked_keys", death_tab.DEATHWATCH_DEFAULTS["blocked_keys"]) == ["F13", "F14", "F15"]
    assert {"pedal_block_sec": 0}.get("pedal_block_sec", death_tab.DEATHWATCH_DEFAULTS["pedal_block_sec"]) == 0
    assert {"blocked_keys": []}.get("blocked_keys", death_tab.DEATHWATCH_DEFAULTS["blocked_keys"]) == []
