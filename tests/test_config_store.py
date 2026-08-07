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


def test_validate_config_non_object_root():
    problems = config_store.validate_config([1, 2, 3])
    assert problems and "not an object" in problems[0]


@pytest.mark.parametrize("key", ["toggles", "combos", "champions", "minimap", "afkfarm"])
def test_validate_config_section_wrong_type(key):
    problems = config_store.validate_config({key: "not-an-object"})
    assert any(key in p for p in problems)


@pytest.mark.parametrize("key", ["mode", "lang"])
def test_validate_config_string_field_wrong_type(key):
    problems = config_store.validate_config({key: 42})
    assert any(key in p for p in problems)


# --- main.load_config corrupt path (integration) ----------------------------

def test_load_config_corrupt_restores_bak(monkeypatch, tmp_path):
    import main as main_mod
    cfg_file = tmp_path / "config.json"
    main_mod.CONFIG_FILE = str(cfg_file)
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
    cfg_file.write_text("{corrupt", encoding="utf-8")

    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning == "corrupt"
    assert cfg["mode"] == main_mod.default_config()["mode"]


def test_load_config_missing_returns_defaults(monkeypatch, tmp_path):
    import main as main_mod
    main_mod.CONFIG_FILE = str(tmp_path / "nope.json")
    main_mod.config_warning = None
    cfg = main_mod.load_config()
    assert main_mod.config_warning is None
    assert cfg["mode"] == main_mod.default_config()["mode"]
