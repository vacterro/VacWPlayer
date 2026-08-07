"""config_store unit tests: atomic write, .bak backup, restore, corrupt config."""

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import config_store


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
        "mode": "ryze", "lang": "ru",
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
    assert config_store.validate_config(hostile) == []


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


def test_import_valid_config_saved(monkeypatch, tmp_path):
    import main as main_mod
    w = object.__new__(main_mod.VacWPlayer)
    w.config = {}
    w.status_lbl = type("S", (), {"config": lambda *a, **k: None})()
    saved = []
    monkeypatch.setattr(main_mod, "save_config", lambda cfg: saved.append(cfg))
    monkeypatch.setattr(main_mod, "load_config",
                        lambda: {"mode": "ryze", "toggles": {}, "combos": [],
                                 "champions": {}, "minimap": {}, "afkfarm": {}})
    monkeypatch.setattr(main_mod.messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(main_mod.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(w, "_rebuild_ui", lambda: None)

    good = tmp_path / "good.json"
    good.write_text('{"mode": "ryze", "toggles": {}, "combos": [], '
                    '"champions": {}, "minimap": {}, "afkfarm": {}, "lang": "en"}',
                    encoding="utf-8")
    w._do_import_file(str(good))
    assert len(saved) == 1      # valid import proceeds
