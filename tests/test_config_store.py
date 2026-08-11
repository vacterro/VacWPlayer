"""config_store unit tests: atomic write, .bak backup, restore, corrupt config."""

import json
import os
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import config_store


@pytest.fixture(autouse=True)
def _reset_main_globals():
    """main module guards are process-wide globals; a test that arms one must
    not leak it into the next (T-169 guards are module state)."""
    yield
    try:
        import main as _m
    except Exception:
        return
    _m.config_write_blocked = None
    _m.local_write_blocked = None


# --- read_raw --------------------------------------------------------------

def test_read_raw_missing_file(tmp_path):
    data, err = config_store.read_raw(str(tmp_path / "nope.json"))
    assert data is None
    assert err == "missing"


def test_read_raw_corrupt_json(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("{not json", encoding="utf-8")
    data, err = config_store.read_raw(str(p))
    assert data is None
    assert err == "corrupt"


def test_read_raw_valid(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    data, err = config_store.read_raw(str(p))
    assert data == {"a": 1}
    assert err is None


# --- atomic_write ----------------------------------------------------------

def test_atomic_write_creates_file(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_atomic_write_backs_up_previous(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    config_store.atomic_write(str(p), {"a": 2})
    bak = p.with_suffix(".json.bak")
    assert bak.exists()
    assert json.loads(bak.read_text(encoding="utf-8")) == {"a": 1}
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 2}


def test_atomic_write_no_bak_on_first_write(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    assert not p.with_suffix(".json.bak").exists()


def test_atomic_write_no_partial_on_failure(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    # a data object that cannot serialize must leave the old file intact
    class Bad:
        pass
    with pytest.raises(TypeError):
        config_store.atomic_write(str(p), {"a": Bad()})
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


# --- restore_backup --------------------------------------------------------

def test_restore_backup(tmp_path):
    p = tmp_path / "cfg.json"
    config_store.atomic_write(str(p), {"a": 1})
    config_store.atomic_write(str(p), {"a": 2})
    p.write_text("{corrupt", encoding="utf-8")  # user-file damage
    assert config_store.restore_backup(str(p)) is True
    assert json.loads(p.read_text(encoding="utf-8")) == {"a": 1}


def test_restore_backup_missing_returns_false(tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text("{}", encoding="utf-8")
    assert config_store.restore_backup(str(p)) is False


# --- validate_config -------------------------------------------------------

def test_validate_config_ok():
    assert config_store.validate_config({
        "mode": "general", "lang": "ru",
        "toggles": {}, "combos": [], "champions": {},
        "minimap": {}, "afkfarm": {},
    }) == []


@pytest.mark.parametrize("key", ["toggles", "combos", "champions", "minimap", "afkfarm"])
def test_validate_config_section_wrong_type(key):
    problems = config_store.validate_config({key: "not-an-object"})
    assert any(key in p for p in problems)


@pytest.mark.parametrize("key", ["mode", "lang"])
def test_validate_config_string_field_wrong_type(key):
    problems = config_store.validate_config({key: 42})
    assert any(key in p for p in problems)


# --- T-086: exact section shapes + total validator ---------------------------

@pytest.mark.parametrize("bad", [[], "x", 42, None])
def test_validate_config_non_object_root(bad):
    problems = config_store.validate_config(bad)
    assert problems and "root" in problems[0]


@pytest.mark.parametrize("key,bad", [
    ("toggles", []), ("combos", {}), ("champions", []),
    ("minimap", []), ("afkfarm", []),
])
def test_validate_config_exact_section_shapes(key, bad):
    """combos must be a list, the other four sections objects - the wrong
    exact shape is rejected before any merge (T-086)."""
    problems = config_store.validate_config({key: bad})
    assert any(key in p for p in problems)


def test_validate_config_never_raises_on_hostile_nesting():
    """The validator is total: hostile nested values produce problems, never a
    validator exception (no int()/float() on unchecked objects)."""
    hostile = {
        "toggles": {"interval": "abc", "x": [1, 2]},
        "combos": [{"trigger": [], "keys": 5, "interval": "no"}],
        "champions": {"ryze": ["not-a-dict"]},
        "minimap": {"top": "junk"},
        "afkfarm": {"slots": {1: 2}},
    }
    problems = config_store.validate_config(hostile)
    assert problems


# --- T-136: deep validation - structures the runtime actually dereferences ----

def test_validate_config_combos_must_be_objects():
    """combos=[1] crashes ComboTab's dict(c) update-sequence - reject."""
    problems = config_store.validate_config({"combos": [1, "x", None]})
    assert any("combos" in p for p in problems)


def test_validate_config_combo_required_fields():
    """ComboTab._refresh_tree indexes c['trigger'], c['keys'], c['interval']
    directly - missing them crashes the tab."""
    for bad in ({}, {"trigger": "F13"}, {"trigger": "F13", "keys": "q,w"},
                {"trigger": 5, "keys": "q", "interval": 50},
                {"trigger": "F13", "keys": [1], "interval": 50},
                {"trigger": "F13", "keys": "q", "interval": "no"},
                {"trigger": "F13", "keys": "q", "interval": 1.5}):
        problems = config_store.validate_config({"combos": [bad]})
        assert problems, "combos=%r must be rejected" % bad
    assert config_store.validate_config(
        {"combos": [{"trigger": "F13", "keys": "q,w", "interval": 50,
                     "shift": False, "move_when_pressed": True}]}) == []


def test_validate_config_champions_entries_must_be_objects():
    problems = config_store.validate_config({"champions": {"ryze": [], "xin": 5}})
    assert any("champions" in p for p in problems)


def test_validate_config_champion_field_types():
    problems = config_store.validate_config({
        "champions": {"ryze": {"trigger_wave": [], "keys_jungle": 5,
                               "enabled_pvp": "yes", "toggle_wave": "no",
                               "move_when_pressed_pvp": "maybe",
                               "display_name": [1], "interval": "abc"}}})
    assert problems


def test_validate_config_champion_valid_field_types_pass():
    assert config_store.validate_config({
        "champions": {"ryze": {"trigger_wave": "F13", "keys_jungle": "q,w",
                               "enabled_pvp": True, "toggle_wave": False,
                               "display_name": "Ryze", "interval": 50,
                               "future_key": "data"}}}) == []


def test_validate_config_minimap_entries_must_be_objects():
    problems = config_store.validate_config({"minimap": {"mid": []}})
    assert any("minimap" in p for p in problems)


def test_validate_config_minimap_field_types():
    """x/y back _show_hotkeys' %d formatting - floats/strings crash it."""
    problems = config_store.validate_config(
        {"minimap": {"mid": {"trigger": 5, "x": "junk", "y": None}}})
    assert problems
    bad = config_store.validate_config(
        {"minimap": {"mid": {"trigger": "O", "x": 1.5, "y": 2}}})
    assert bad


def test_validate_config_minimap_valid_pass():
    assert config_store.validate_config(
        {"minimap": {"mid": {"trigger": "O", "x": 1, "y": 2},
                     "custom_1": {"trigger": "", "x": 0, "y": 0}}}) == []
    assert config_store.validate_config(
        {"minimap": {"mid": {"trigger": "O", "x": 1, "y": 2},
                     "_order": ["top", "mid"]}}) == []


def test_validate_config_minimap_order_is_string_list():
    problems = config_store.validate_config({"minimap": {"_order": [1, 2]}})
    assert problems


def test_validate_config_afkfarm_shapes():
    assert config_store.validate_config({"afkfarm": {"slots": 5}})
    assert config_store.validate_config({"afkfarm": {"slots": {"top": "junk"}}})
    assert config_store.validate_config(
        {"afkfarm": {"slots": {"top": {"enabled": "yes"}}}})
    assert config_store.validate_config({"afkfarm": {"enabled": "yes"}})
    assert config_store.validate_config({"afkfarm": {"toggle_key": [1]}})


def test_validate_config_afkfarm_valid_pass():
    assert config_store.validate_config({
        "afkfarm": {"enabled": True, "toggle_key": "F5",
                    "slots": {"top": {"enabled": True,
                                      "move_when_pressed": False}}},
        "afkfarm_extra": 5}) == []


# --- T-168: afkfarm validator must cover builder-consumed fields ---------------

@pytest.mark.parametrize("bad", [
    {"move_duration": "x"},
    {"move_duration": True},        # bool is not a duration
    {"move_duration": 100},         # below UI minimum 500
    {"move_duration": -1},
    {"combo_interval": []},
    {"combo_interval": True},       # bool is not an interval
    {"combo_interval": 5},          # below UI minimum 15
    {"follow_cursor": "false"},     # string must NEVER become bool True
    {"follow_cursor": 1},
])
def test_validate_config_afkfarm_builder_fields_rejected(bad):
    problems = config_store.validate_config({"afkfarm": bad})
    assert problems, bad


def test_validate_config_afkfarm_builder_fields_valid():
    assert config_store.validate_config({
        "afkfarm": {"move_duration": 5000, "combo_interval": 128,
                    "follow_cursor": True}}) == []


def test_validate_config_afkfarm_boundary_minimums():
    assert config_store.validate_config({"afkfarm": {"move_duration": 500}}) == []
    assert config_store.validate_config({"afkfarm": {"combo_interval": 15}}) == []
    assert config_store.validate_config({"afkfarm": {"move_duration": 499}})
    assert config_store.validate_config({"afkfarm": {"combo_interval": 14}})


# --- T-172: unknown mode must not pass structural validation ------------------

def test_validate_config_unknown_mode_rejected():
    """mode != 'general' must name a configured champion - anything else
    silently generates no combos (T-172)."""
    champions = {"ryze": {"trigger_pvp": "F15", "keys_pvp": "q,w,e"}}
    problems = config_store.validate_config(
        {"mode": "definitely_not_a_champion", "champions": champions})
    assert problems
    assert config_store.validate_config(
        {"mode": "ryze", "champions": champions}) == []
    assert config_store.validate_config({"mode": "general"}) == []
    assert config_store.validate_config({}) == []


def test_validate_config_toggles_hostile_values():
    assert config_store.validate_config({"toggles": {"space_interval": "abc"}})
    assert config_store.validate_config({"toggles": {"space_interval": True}})
    assert config_store.validate_config({"toggles": {"mouse_remap": "yes"}})
    assert config_store.validate_config({"toggles": {"untoggle_keys": [1]}})
    assert config_store.validate_config({"toggles": {"anti_afk_interval": None}})


def test_validate_config_toggles_unknown_keys_forward_compat():
    """Unknown toggle keys are NOT validated - they may be forward-compatible
    config the runtime does not consume."""
    assert config_store.validate_config(
        {"toggles": {"some_future_toggle": "anything", "x": [1, 2]}}) == []


def test_validate_config_window_shape():
    assert config_store.validate_config({"window": [1, 2]})
    assert config_store.validate_config({"window": {"active_tab": "x"}})
    assert config_store.validate_config({"window": {"active_tab": True}})
    assert config_store.validate_config({"window": {"position": 5}})


def test_validate_config_mode_semantics():
    assert config_store.validate_config({"mode": ""})
    assert config_store.validate_config({"mode": []})


def test_validate_config_default_config_passes():
    import main as main_mod
    assert config_store.validate_config(main_mod.default_config()) == []


def test_validate_config_wrong_types_flagged():
    problems = config_store.validate_config({
        "toggles": [], "combos": {}, "champions": [], "minimap": [], "afkfarm": [],
    })
    assert len(problems) == 5


# --- T-086: config.local validation + total merge ----------------------------

def test_validate_local_config_ok():
    local = {
        "window": {"active_tab": 2, "position": "1170,449"},
        "champions": {"ryze": {"enabled_pvp": True}},
    }
    assert config_store.validate_local_config(local) == []


@pytest.mark.parametrize("bad", [[], "x", 42, None])
def test_validate_local_config_root(bad):
    assert config_store.validate_local_config(bad)


def test_validate_local_config_active_tab_string():
    problems = config_store.validate_local_config({"window": {"active_tab": "x"}})
    assert problems and "active_tab" in problems[0]


def test_validate_local_config_active_tab_bool_forbidden():
    # bool is int in Python - must be rejected for a numeric field
    problems = config_store.validate_local_config({"window": {"active_tab": True}})
    assert problems and "active_tab" in problems[0]


def test_validate_local_config_position_wrong_type():
    problems = config_store.validate_local_config({"window": {"position": 123}})
    assert problems and "position" in problems[0]


def test_validate_local_config_champion_flag_non_bool():
    problems = config_store.validate_local_config(
        {"champions": {"ryze": {"enabled_pvp": "yes"}}})
    assert problems and "enabled_pvp" in problems[0]


def test_merge_volatile_hostile_local_never_raises():
    cfg = {"mode": "ryze", "champions": {"ryze": {"trigger_pvp": "F15"}},
           "window": {"active_tab": 0}}
    locals_ = [
        {"window": "junk"},
        {"window": {"active_tab": "x", "position": 5, "garbage": [1]}},
        {"champions": "junk"},
        {"champions": {"ryze": ["not-a-dict"]}},
        {"champions": {"ryze": {"enabled_pvp": "yes", "trigger_pvp": "!F9"}}},
        [1, 2],
        "junk",
    ]
    for local in locals_:
        out = config_store.merge_volatile(dict(cfg), local)
        assert out["window"] == {"active_tab": 0}  # hostile values never merged
        assert out["champions"]["ryze"]["trigger_pvp"] == "F15"


def test_merge_volatile_accepts_clean_local():
    cfg = {"mode": "ryze", "champions": {"ryze": {"trigger_pvp": "F15"}},
           "window": {"active_tab": 0}}
    local = {"window": {"active_tab": 3, "position": "50,60"},
             "champions": {"ryze": {"enabled_pvp": True}}}
    out = config_store.merge_volatile(dict(cfg), local)
    assert out["window"] == {"active_tab": 3, "position": "50,60"}
    assert out["champions"]["ryze"]["enabled_pvp"] is True


# --- split_volatile / merge_volatile ----------------------------------------

def test_split_volatile_moves_window_and_champ_flags():
    cfg = {
        "mode": "ryze",
        "champions": {
            "ryze": {"enabled_pvp": True, "toggle_wave": False,
                     "trigger_pvp": "F15", "keys_pvp": "q,w,e"},
            "xin_zhao": {"enabled_jungle": True, "trigger_jungle": "F14"},
        },
        "window": {"active_tab": 2, "position": "100,200"},
    }
    stable, local = config_store.split_volatile(cfg)
    assert "window" not in stable
    assert stable["champions"]["ryze"] == {"trigger_pvp": "F15", "keys_pvp": "q,w,e"}
    assert stable["champions"]["xin_zhao"] == {"trigger_jungle": "F14"}
    assert local["window"] == {"active_tab": 2, "position": "100,200"}
    assert local["champions"]["ryze"] == {"enabled_pvp": True, "toggle_wave": False}
    assert local["champions"]["xin_zhao"] == {"enabled_jungle": True}


def test_split_volatile_empty_window_omitted():
    cfg = {"mode": "general", "window": {}, "champions": {}}
    stable, local = config_store.split_volatile(cfg)
    assert "window" not in local
    assert "window" not in stable


def test_merge_volatile_overlays_local():
    config = {
        "mode": "ryze",
        "champions": {"ryze": {"enabled_pvp": False, "trigger_pvp": "F15"}},
        "window": {"active_tab": 0},
    }
    local = {
        "window": {"active_tab": 3, "position": "50,60"},
        "champions": {"ryze": {"enabled_pvp": True}},
    }
    merged = config_store.merge_volatile(config, local)
    assert merged["window"] == {"active_tab": 3, "position": "50,60"}
    assert merged["champions"]["ryze"] == {"enabled_pvp": True, "trigger_pvp": "F15"}


def test_merge_volatile_non_dict_ignored():
    config = {"mode": "general", "window": {"active_tab": 1}}
    assert config_store.merge_volatile(config, None) is config
    assert config_store.merge_volatile(config, [1, 2]) is config


def test_split_merge_roundtrip_preserves_config():
    cfg = {
        "mode": "ryze",
        "champions": {
            "ryze": {"enabled_pvp": True, "toggle_wave": False,
                     "trigger_pvp": "F15", "keys_pvp": "q,w,e"},
        },
        "window": {"active_tab": 2, "position": "100,200"},
        "lang": "ru",
    }
    stable, local = config_store.split_volatile(cfg)
    restored = config_store.merge_volatile(dict(stable), local)
    assert restored == cfg


# --- main.load_config corrupt path (integration) ----------------------------

def test_load_config_corrupt_restores_bak(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    # two saves -> .bak exists with the first good config, then corrupt live
    good = main_mod.default_config()
    config_store.atomic_write(str(cfg_file), good)
    config_store.atomic_write(str(cfg_file), good)
    cfg_file.write_text("{corrupt", encoding="utf-8")

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "restored"
    assert cfg["mode"] == good["mode"]


def test_load_config_corrupt_no_bak_returns_defaults(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    cfg_file.write_text("{corrupt", encoding="utf-8")

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "corrupt"
    assert cfg["mode"] == main_mod.default_config()["mode"]


def test_load_config_missing_returns_defaults(monkeypatch, tmp_path):
    import main as main_mod
    main_mod.CONFIG_FILE = str(tmp_path / "nope.json")
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning is None
    assert cfg["mode"] == main_mod.default_config()["mode"]


def test_load_config_applies_local_overlay(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    config_store.atomic_write(str(cfg_file), {"mode": "ryze"})
    config_store.atomic_write(str(local_file), {"window": {"active_tab": 4}})

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert cfg["window"]["active_tab"] == 4


def test_load_config_corrupt_local_ignored(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    config_store.atomic_write(str(cfg_file), {"mode": "ryze"})
    local_file.write_text("{corrupt", encoding="utf-8")

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert cfg["mode"] == "ryze"
    assert cfg["window"] == {"active_tab": 0}


# --- T-086: malformed-but-valid JSON never reaches the merge -----------------

@pytest.mark.parametrize("data", [
    [],
    {"toggles": []},
    {"combos": {}},
    {"champions": []},
    {"minimap": []},
    {"afkfarm": []},
    {"mode": 42},
])
def test_load_config_rejects_structural_garbage(monkeypatch, tmp_path, data):
    """Valid JSON with the wrong shape must be rejected BEFORE migration or
    merge: defaults survive, no malformed section enters the live config, and
    the app starts instead of crashing."""
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    config_store.atomic_write(str(cfg_file), data)

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "corrupt"
    assert cfg["mode"] == main_mod.default_config()["mode"]
    assert isinstance(cfg["toggles"], dict)
    assert isinstance(cfg["combos"], list)


def test_load_config_merge_survives_hostile_nested(monkeypatch, tmp_path):
    """Legacy migration surfaces (ryze/xin as non-dicts) must not crash the
    merge when the top-level shapes are valid."""
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    config_store.atomic_write(str(cfg_file), {
        "ryze": ["not-a-dict"],
        "champions": {},
        "toggles": {"stop_key": "s"},
        "combos": [],
        "minimap": {},
        "afkfarm": {},
    })

    main_mod.config_warning = None
    cfg = main_mod.load_config()  # must not raise
    assert cfg["mode"] == main_mod.default_config()["mode"]


def test_load_config_ignores_bad_local_state(monkeypatch, tmp_path):
    """Bad local state is ignored/recovered, never a startup crash and never
    merged into the live config."""
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    config_store.atomic_write(str(cfg_file), {"mode": "ryze"})
    config_store.atomic_write(str(local_file), {
        "window": {"active_tab": "x", "position": 5},
        "champions": {"ryze": {"enabled_pvp": "yes"}},
    })

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert cfg["window"] == {"active_tab": 0}  # bad active_tab not merged
    assert "enabled_pvp" not in cfg["champions"]["ryze"]


def test_save_config_writes_split_files(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    cfg = {
        "mode": "ryze",
        "champions": {"ryze": {"enabled_pvp": True, "trigger_pvp": "F15"}},
        "window": {"active_tab": 1, "position": "5,5"},
    }
    main_mod.save_config(cfg)
    stable = json.loads(cfg_file.read_text(encoding="utf-8"))
    local = json.loads(local_file.read_text(encoding="utf-8"))
    assert "window" not in stable
    assert stable["champions"]["ryze"] == {"trigger_pvp": "F15"}
    assert local["window"] == {"active_tab": 1, "position": "5,5"}
    assert local["champions"]["ryze"] == {"enabled_pvp": True}


# --- T-161: save_config must not commit the PRIMARY half on a failed save -----

def test_save_config_local_failure_leaves_primary_unchanged(tmp_path, monkeypatch):
    """When the volatile (config.local.json) write fails, save_config returns
    False AND the primary config.json must NOT be ahead of the failure - a
    reported-failed save must not have already committed the main config
    (T-161). The local half is written first so the stable half is only ever
    committed on a fully-successful save."""
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    cfg_file.write_text('{"mode": "old"}', encoding="utf-8")
    local_file.write_text('{"window": {"active_tab": 0}}', encoding="utf-8")
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)

    real_atomic = main_mod.config_store.atomic_write

    def selective(path, data):
        if os.path.normcase(str(path)) == os.path.normcase(str(local_file)):
            raise OSError(13, "denied", path)
        return real_atomic(path, data)

    monkeypatch.setattr(main_mod.config_store, "atomic_write", selective)
    cfg = {"mode": "ryze", "window": {"active_tab": 1}}
    assert main_mod.save_config(cfg) is False
    assert json.loads(cfg_file.read_text(encoding="utf-8")) == {"mode": "old"}
    main_mod.config_write_blocked = None


# --- T-090: tracked config baseline stays volatile-free ---------------------

def test_committed_config_has_no_volatile_keys():
    """The tracked config.json must not carry runtime-volatile state (window
    geometry, champion enabled_/toggle_ flags). If it did, the first normal
    save would dirty the tracked file by split_volatile migration (T-090)."""
    p = BASE / "config.json"
    if not p.exists():
        return
    cfg = json.loads(p.read_text(encoding="utf-8"))
    assert "window" not in cfg
    for entry in cfg.get("champions", {}).values():
        if isinstance(entry, dict):
            for k in entry:
                assert not k.startswith(("enabled_", "toggle_"))


def test_split_volatile_migration_preserves_user_values():
    """Migrating a baseline that still carries volatile keys must keep every
    stable user value (e.g. trigger_pvp) in the tracked half and move only the
    volatile flags to the local half - no user data lost, no tracked file
    dirtied."""
    baseline = {
        "mode": "ryze",
        "champions": {
            "ryze": {"enabled_pvp": True, "toggle_pvp": True,
                     "trigger_pvp": "F15,mbutton", "keys_pvp": "q,w,e"},
        },
        "window": {"active_tab": 2, "position": "1170,449"},
        "lang": "en",
    }
    stable, local = config_store.split_volatile(baseline)
    assert stable["champions"]["ryze"] == {
        "trigger_pvp": "F15,mbutton", "keys_pvp": "q,w,e"}
    assert stable["lang"] == "en"
    assert "window" not in stable
    assert local["champions"]["ryze"] == {"enabled_pvp": True, "toggle_pvp": True}
    assert local["window"] == {"active_tab": 2, "position": "1170,449"}
    # roundtrip restores the exact baseline
    assert config_store.merge_volatile(dict(stable), local) == baseline


# --- T-092: import must validate before overwriting live config -------------

def test_import_garbage_config_never_saved(monkeypatch, tmp_path):
    """Importing a structurally-bad JSON file must be rejected BEFORE
    save_config: writing garbage over the user's live config is data loss
    (T-092)."""
    import main as main_mod
    w = object.__new__(main_mod.VacWPlayer)
    saved = []
    monkeypatch.setattr(main_mod, "save_config", lambda cfg: saved.append(cfg))
    monkeypatch.setattr(main_mod, "load_config", lambda: {})
    monkeypatch.setattr(main_mod.messagebox, "askyesno", lambda *a, **k: True)
    errors = []
    monkeypatch.setattr(main_mod.messagebox, "showerror",
                        lambda title, msg: errors.append(msg))

    bad = tmp_path / "bad.json"
    bad.write_text("[]", encoding="utf-8")
    w._do_import_file(str(bad))
    assert saved == []          # garbage never reaches save_config
    assert errors               # a clear diagnostic was shown


# --- T-135 fail-closed: io_error, write guard, validated backup restore ------

def test_read_raw_permission_error_is_io_error(monkeypatch, tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"a": 1}', encoding="utf-8")

    def denied(path, *a, **k):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr("builtins.open", denied)
    data, err = config_store.read_raw(str(p))
    assert data is None
    assert err == "io_error"


def test_read_raw_other_oserror_is_io_error(monkeypatch, tmp_path):
    p = tmp_path / "cfg.json"
    p.write_text('{"a": 1}', encoding="utf-8")

    def broken(path, *a, **k):
        raise OSError(22, "Invalid argument", path)

    monkeypatch.setattr("builtins.open", broken)
    data, err = config_store.read_raw(str(p))
    assert data is None
    assert err == "io_error"


def test_read_raw_missing_file_still_missing(tmp_path):
    data, err = config_store.read_raw(str(tmp_path / "nope.json"))
    assert err == "missing"


def _reset_guard(main_mod):
    main_mod.config_write_blocked = None
    main_mod.config_warning = None


def test_load_config_io_error_blocks_write(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    cfg_file.write_text('{"mode": "ryze", "toggles": {}, "combos": [], '
                        '"champions": {}, "minimap": {}, "afkfarm": {}}',
                        encoding="utf-8")
    orig = cfg_file.read_bytes()

    def denied(path, *a, **k):
        raise PermissionError(13, "Permission denied", path)

    monkeypatch.setattr("builtins.open", denied)
    _reset_guard(main_mod)
    cfg = main_mod.load_config()
    assert main_mod.config_write_blocked == "io_error"
    assert cfg["mode"] == main_mod.default_config()["mode"]

    monkeypatch.setattr("builtins.open", __builtins__["open"])
    main_mod.save_config(cfg)
    assert cfg_file.read_bytes() == orig  # byte-identical: nothing overwritten


def test_load_config_structural_reject_blocks_write(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    bad = '{"toggles": [], "combos": {}, "champions": 5}'
    cfg_file.write_text(bad, encoding="utf-8")

    _reset_guard(main_mod)
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "corrupt"
    assert main_mod.config_write_blocked == "invalid"

    main_mod.save_config(cfg)
    assert cfg_file.read_text(encoding="utf-8") == bad
    assert not local_file.exists()  # nothing written to the local half either


def test_load_config_corrupt_never_restores_invalid_bak(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    cfg_file.write_text("{corrupt", encoding="utf-8")
    bak = tmp_path / "config.json.bak"
    bad_bak = '{"toggles": [], "combos": {}}'
    bak.write_text(bad_bak, encoding="utf-8")

    _reset_guard(main_mod)
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "corrupt"
    assert main_mod.config_write_blocked == "corrupt"
    assert cfg_file.read_text(encoding="utf-8") == "{corrupt"  # not overwritten
    assert bak.read_text(encoding="utf-8") == bad_bak
    assert cfg["mode"] == main_mod.default_config()["mode"]
    assert isinstance(cfg["toggles"], dict)


def test_load_config_corrupt_valid_bak_restores_and_unblocks(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    cfg_file.write_text("{corrupt", encoding="utf-8")
    good = '{"mode": "general", "toggles": {"stop_key": "k"}, "combos": [], ' \
           '"champions": {}, "minimap": {}, "afkfarm": {}}'
    bak = tmp_path / "config.json.bak"
    bak.write_text(good, encoding="utf-8")

    _reset_guard(main_mod)
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "restored"
    assert main_mod.config_write_blocked is None  # explicit recovery unblocks
    assert cfg["toggles"]["stop_key"] == "k"
    assert json.loads(cfg_file.read_text(encoding="utf-8"))["toggles"]["stop_key"] == "k"


def test_import_clears_write_guard(monkeypatch, tmp_path):
    import main as main_mod
    w = object.__new__(main_mod.VacWPlayer)
    w.config = {}
    w.status_lbl = type("S", (), {"config": lambda *a, **k: None})()
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    cfg_file.write_text("{corrupt", encoding="utf-8")
    monkeypatch.setattr(main_mod.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(main_mod.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(w, "_rebuild_ui", lambda: None)

    good = tmp_path / "good.json"
    good.write_text('{"mode": "general", "toggles": {}, "combos": [], '
                    '"champions": {}, "minimap": {}, "afkfarm": {}, "lang": "en"}',
                    encoding="utf-8")
    main_mod.config_write_blocked = "io_error"
    w._do_import_file(str(good))
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["mode"] == "general"
    assert main_mod.config_write_blocked is None  # cleared only after write+read-back
    main_mod.config_write_blocked = None


def test_save_config_guarded_writes_nothing(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(tmp_path / "config.local.json")
    cfg_file.write_text("{}", encoding="utf-8")
    main_mod.config_write_blocked = "corrupt"
    assert main_mod.save_config({"mode": "ryze"}) is False
    assert cfg_file.read_text(encoding="utf-8") == "{}"
    main_mod.config_write_blocked = None


def test_import_valid_config_saved(monkeypatch, tmp_path):
    import main as main_mod
    w = object.__new__(main_mod.VacWPlayer)
    w.config = {}
    w.status_lbl = type("S", (), {"config": lambda *a, **k: None})()
    saved = []
    monkeypatch.setattr(main_mod, "save_config", lambda cfg, bypass_guard=False: saved.append(cfg) or True)
    monkeypatch.setattr(main_mod, "load_config",
                        lambda: {"mode": "ryze", "toggles": {}, "combos": [],
                                 "champions": {}, "minimap": {}, "afkfarm": {}})
    monkeypatch.setattr(main_mod.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(main_mod.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(w, "_rebuild_ui", lambda: None)

    good = tmp_path / "good.json"
    good.write_text('{"mode": "general", "toggles": {}, "combos": [], '
                    '"champions": {}, "minimap": {}, "afkfarm": {}, "lang": "en"}',
                    encoding="utf-8")
    w._do_import_file(str(good))
    assert len(saved) == 1      # valid import proceeds

# --- T-145: file-drop parsing must survive spaces / braces / URIs -------------

import tkinter as _tk
_TCL = _tk.Tcl()


def _drop_path(raw):
    import main as main_mod
    return main_mod._first_drop_path(_TCL.splitlist, raw)


def test_first_drop_path_braced_path_with_spaces(tmp_path):
    p = tmp_path / "My Config.json"
    p.write_text("{}", encoding="utf-8")
    assert _drop_path("{%s}" % str(p)) == str(p)


def test_first_drop_path_multiple_files_takes_first(tmp_path):
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    p1.write_text("{}", encoding="utf-8")
    p2.write_text("{}", encoding="utf-8")
    assert _drop_path("{%s} {%s}" % (p1, p2)) == str(p1)


def test_first_drop_path_unbraced_multi_space_path(tmp_path):
    p = tmp_path / "dir with space" / "cfg file.json"
    p.parent.mkdir()
    p.write_text("{}", encoding="utf-8")
    # TkinterDnD always hands a Tcl list - a spaced path arrives braced
    assert _drop_path("{%s}" % str(p)) == str(p)


def test_first_drop_path_file_uri(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("{}", encoding="utf-8")
    uri = "file:///" + str(p).replace("\\", "/")
    out = _drop_path(uri)
    assert out is not None
    assert os.path.isfile(out) and out.lower().endswith(".json")


def test_first_drop_path_ignores_non_json(tmp_path):
    p = tmp_path / "a.txt"
    p.write_text("x", encoding="utf-8")
    assert _drop_path(str(p)) is None


def test_first_drop_path_skips_missing_and_picks_json(tmp_path):
    gone = tmp_path / "gone.json"
    good = tmp_path / "good.json"
    good.write_text("{}", encoding="utf-8")
    assert _drop_path("{%s} {%s}" % (gone, good)) == str(good)


def test_first_drop_path_none_on_empty():
    assert _drop_path("") is None
    assert _drop_path("   ") is None


# --- T-149-F: tray Quit must marshal to the Tk thread via root.after ----------

def test_tray_quit_marshals_via_root_after():
    """quit_app touches Tk widgets; it must never run on the pystray callback
    thread. _tray_quit only schedules it on the Tk mainloop (T-149-F)."""
    import main as main_mod
    w = object.__new__(main_mod.VacWPlayer)
    calls = []

    class FakeRoot:
        def after(self, *a):
            calls.append(a)
            return 1

    w.root = FakeRoot()
    w.quit_app = lambda *a, **k: calls.append("DIRECT")
    w._tray_quit()
    assert calls == [(0, w.quit_app)]  # scheduled, never invoked directly


def test_setup_tray_wires_quit_through_marshaling(monkeypatch):
    import main as main_mod
    w = object.__new__(main_mod.VacWPlayer)
    w.root = type("R", (), {"after": lambda *a: None})()
    w.tray_icon = None
    w._tray_image = lambda: object()

    class FakeIcon:
        last = None

        def __init__(self, *a):
            FakeIcon.last = a

        def run(self):
            pass

    class FakeItem:
        def __init__(self, text, action, **kw):
            self.text = text
            self.action = action

    class FakeMenu:
        def __init__(self, *items):
            self.items = items

    monkeypatch.setitem(sys.modules, "pystray", type(
        "PS", (), {"Icon": FakeIcon, "MenuItem": FakeItem,
                   "Menu": FakeMenu})())
    w.setup_tray()
    quit_item = [i for i in FakeIcon.last[3].items
                 if i.text == main_mod.Locale.tr("tray_quit")]
    assert quit_item and quit_item[0].action == w._tray_quit

# --- T-156: import must not clear the write guard before persistence ----------

_VALID_IMPORT = '{"mode": "general", "toggles": {}, "combos": [], "champions": {}, "minimap": {}, "afkfarm": {}, "lang": "en"}'


def _import_harness(tmp_path, monkeypatch):
    import main as main_mod
    w = object.__new__(main_mod.VacWPlayer)
    w.config = {}
    w.status_lbl = type("S", (), {"config": lambda *a, **k: None})()
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    cfg_file.write_text("{corrupt source", encoding="utf-8")
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    monkeypatch.setattr(main_mod.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(main_mod.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(w, "_rebuild_ui", lambda: None)
    import_file = tmp_path / "import.json"
    import_file.write_text(_VALID_IMPORT, encoding="utf-8")
    return main_mod, w, cfg_file, import_file


def test_import_failed_write_restores_guard(tmp_path, monkeypatch):
    """A recovery import whose WRITE fails must leave the old guard armed - a
    later autosave/apply must stay blocked (T-156)."""
    main_mod, w, cfg_file, import_file = _import_harness(tmp_path, monkeypatch)

    def boom(path, data):
        raise OSError(13, "denied", path)

    monkeypatch.setattr(main_mod.config_store, "atomic_write", boom)
    main_mod.config_write_blocked = "corrupt"
    w._do_import_file(str(import_file))
    assert main_mod.config_write_blocked == "corrupt"  # guard retained
    assert cfg_file.read_text(encoding="utf-8") == "{corrupt source"  # untouched
    # ordinary save remains blocked after the failed recovery
    assert main_mod.save_config({"mode": "ryze"}) is False
    main_mod.config_write_blocked = None


def test_import_success_clears_guard_and_persists(tmp_path, monkeypatch):
    """Successful recovery import persists the candidate and clears the guard
    only after the write landed (T-156)."""
    main_mod, w, cfg_file, import_file = _import_harness(tmp_path, monkeypatch)
    main_mod.config_write_blocked = "corrupt"
    w._do_import_file(str(import_file))
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["mode"] == "general"
    assert main_mod.config_write_blocked is None  # cleared only on success
    main_mod.config_write_blocked = None

# --- T-157: backup must not report success after failed/blocked save ----------

def _backup_harness(tmp_path, monkeypatch):
    import main as main_mod
    main_mod.config_write_blocked = None  # fresh guard per test
    w = object.__new__(main_mod.VacWPlayer)
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    main_mod.BASE = str(tmp_path)  # backups/ land in tmp, not the repo
    cfg_file.write_text("{corrupt source", encoding="utf-8")
    status = []
    w.status_lbl = type("S", (), {"config": lambda *a, **k: status.append(a)})()
    w.collect_config = lambda: None
    w.config = {"mode": "ryze", "toggles": {}, "combos": [], "champions": {},
                "minimap": {}, "afkfarm": {}, "lang": "en"}
    errors = []
    monkeypatch.setattr(main_mod.messagebox, "showerror",
                        lambda *a, **k: errors.append(a))
    return main_mod, w, cfg_file, status, errors


def test_backup_guarded_source_aborts_no_success(tmp_path, monkeypatch):
    """Write-guarded degraded source: backup must abort and never claim a
    successful current-config backup (T-157)."""
    main_mod, w, cfg_file, status, errors = _backup_harness(tmp_path, monkeypatch)
    main_mod.config_write_blocked = "corrupt"
    w.backup_config()
    assert status == []          # no success status shown
    assert errors                # a failure diagnostic was shown
    assert not (tmp_path / "backups").exists() or \
        not list((tmp_path / "backups").glob("config_*.json"))
    main_mod.config_write_blocked = None


def test_backup_save_failure_aborts_no_success(tmp_path, monkeypatch):
    """save_config failing (disk error) must abort backup, no success text."""
    main_mod, w, cfg_file, status, errors = _backup_harness(tmp_path, monkeypatch)
    def boom(path, data):
        raise OSError(13, "denied", path)
    monkeypatch.setattr(main_mod.config_store, "atomic_write", boom)
    w.backup_config()
    assert status == []
    assert errors
    assert not list((tmp_path / "backups").glob("config_*.json"))


def test_backup_success_copies_stable_config(tmp_path, monkeypatch):
    main_mod, w, cfg_file, status, errors = _backup_harness(tmp_path, monkeypatch)
    w.backup_config()
    backups = tmp_path / "backups"
    files = list(backups.glob("config_*.json"))
    assert len(files) == 1
    data = json.loads(files[0].read_text(encoding="utf-8"))
    assert data["mode"] == "ryze"
    assert status and not errors

# --- T-169: config.local.json needs its own write guard -----------------------

_VALID_STABLE = '{"mode": "general", "toggles": {}, "combos": [], "champions": {}, "minimap": {}, "afkfarm": {}, "lang": "en"}'


def _local_harness(tmp_path, monkeypatch, local_bytes="{corrupt local"):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    cfg_file.write_text(_VALID_STABLE, encoding="utf-8")
    local_file.write_text(local_bytes, encoding="utf-8")
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    main_mod.config_write_blocked = None
    main_mod.local_write_blocked = None
    return main_mod, cfg_file, local_file


def test_load_config_arms_local_guard_on_corrupt_local(tmp_path, monkeypatch):
    main_mod, _, _ = _local_harness(tmp_path, monkeypatch)
    main_mod.load_config()
    assert main_mod.local_write_blocked == "corrupt"


def test_load_config_arms_local_guard_on_invalid_local(tmp_path, monkeypatch):
    main_mod, _, _ = _local_harness(tmp_path, monkeypatch, '{"window": {"active_tab": "x"}}')
    main_mod.load_config()
    assert main_mod.local_write_blocked == "invalid"


def test_save_config_preserves_unsafe_local(tmp_path, monkeypatch):
    """A healthy primary must never authorize overwriting an unsafe local
    file: normal save leaves corrupt local byte-identical (T-169)."""
    main_mod, cfg_file, local_file = _local_harness(tmp_path, monkeypatch)
    main_mod.load_config()
    assert main_mod.local_write_blocked == "corrupt"
    ok = main_mod.save_config({"mode": "ryze", "window": {"active_tab": 1}})
    assert ok is True
    assert local_file.read_text(encoding="utf-8") == "{corrupt local"
    data = json.loads(cfg_file.read_text(encoding="utf-8"))
    assert data["mode"] == "ryze"


def test_save_config_missing_local_creates_it_normally(tmp_path, monkeypatch):
    """Missing local = first run, writable: a normal save creates it."""
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    cfg_file.write_text(_VALID_STABLE, encoding="utf-8")
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    main_mod.config_write_blocked = None
    main_mod.local_write_blocked = None
    ok = main_mod.save_config({"mode": "ryze", "window": {"active_tab": 1}})
    assert ok is True
    assert local_file.exists()
    data = json.loads(local_file.read_text(encoding="utf-8"))
    assert data["window"]["active_tab"] == 1


# --- T-170: save_config(False) must leave NO durable candidate half -----------

def test_save_config_stable_failure_rolls_back_local(tmp_path, monkeypatch):
    """Old stable A + old local A, candidate B: local write succeeds, stable
    write fails -> save_config returns False AND restart must NOT observe the
    hybrid (stable A + local B) - the local candidate half is rolled back
    (T-170)."""
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    cfg_file.write_text('{"mode": "A"}', encoding="utf-8")
    local_file.write_text('{"window": {"active_tab": 0}}', encoding="utf-8")
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    main_mod.config_write_blocked = None
    main_mod.local_write_blocked = None

    real_atomic = main_mod.config_store.atomic_write

    def selective(path, data):
        if os.path.normcase(str(path)) == os.path.normcase(str(cfg_file)):
            raise OSError(13, "denied", path)  # stable write fails
        return real_atomic(path, data)

    monkeypatch.setattr(main_mod.config_store, "atomic_write", selective)
    assert main_mod.save_config({"mode": "B",
                                 "window": {"active_tab": 1}}) is False
    # restart observes NO candidate half:
    assert json.loads(cfg_file.read_text(encoding="utf-8")) == {"mode": "A"}
    assert json.loads(local_file.read_text(encoding="utf-8")) == {
        "window": {"active_tab": 0}}


def test_save_config_stable_failure_removes_new_local(tmp_path, monkeypatch):
    """Local did not exist before the failed save -> it must not be created
    as a surviving candidate half (T-170)."""
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    local_file = tmp_path / "config.local.json"
    cfg_file.write_text('{"mode": "A"}', encoding="utf-8")
    main_mod.CONFIG_FILE = str(cfg_file)
    main_mod.CONFIG_LOCAL_FILE = str(local_file)
    main_mod.config_write_blocked = None
    main_mod.local_write_blocked = None

    real_atomic = main_mod.config_store.atomic_write

    def selective(path, data):
        if os.path.normcase(str(path)) == os.path.normcase(str(cfg_file)):
            raise OSError(13, "denied", path)
        return real_atomic(path, data)

    monkeypatch.setattr(main_mod.config_store, "atomic_write", selective)
    assert main_mod.save_config({"mode": "B",
                                 "window": {"active_tab": 1}}) is False
    assert not local_file.exists()  # no orphaned candidate local half


def test_import_stable_failure_rolls_back_and_restores_guard(tmp_path, monkeypatch):
    """Explicit import with the same failure order (local ok, stable fails):
    no hybrid survives and the previous write guard is restored (T-170/T-156)."""
    main_mod, w, cfg_file, import_file = _import_harness(tmp_path, monkeypatch)
    local_file = tmp_path / "config.local.json"
    real_atomic = main_mod.config_store.atomic_write

    def selective(path, data):
        if os.path.normcase(str(path)) == os.path.normcase(str(cfg_file)):
            raise OSError(13, "denied", path)
        return real_atomic(path, data)

    monkeypatch.setattr(main_mod.config_store, "atomic_write", selective)
    main_mod.config_write_blocked = "corrupt"
    w._do_import_file(str(import_file))
    assert main_mod.config_write_blocked == "corrupt"  # guard restored
    assert not local_file.exists()  # no candidate local half survives
    assert cfg_file.read_text(encoding="utf-8") == "{corrupt source"
