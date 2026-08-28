"""CORE-002 regression: transaction journal is mandatory precondition.

These tests pin the audit's repair contract for _txn_write / _txn_recover /
save_config / load_config. The journal publication must be:
  - returned (not silently swallowed) so save_config can abort
  - blocking load_config when the live halves are inconsistent
  - retained on rollback failure so next launch can attempt recovery
"""

import base64
import json
import os
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import main as main_mod  # noqa: E402


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Redirect CONFIG_FILE, CONFIG_LOCAL_FILE, _TXN_FILE to tmp_path."""
    monkeypatch.setattr(main_mod, "BASE", str(tmp_path))
    monkeypatch.setattr(main_mod, "CONFIG_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(main_mod, "CONFIG_LOCAL_FILE", str(tmp_path / "config.local.json"))
    monkeypatch.setattr(main_mod, "_TXN_FILE", str(tmp_path / "config.local.json.txn"))
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level write guards after every test: save_config and
    load_config mutate them, and leaked values poison later tests. Also
    restore the module-original _TXN_FILE so a retained journal cannot leak
    into other test modules' load_config calls."""
    yield
    main_mod.config_write_blocked = None
    main_mod.local_write_blocked = None
    main_mod.config_warning = None
    main_mod.local_warning = None
    main_mod._TXN_FILE = str(Path(main_mod.BASE) / "config.local.json.txn")

def test_txn_write_returns_true_on_success(isolated):
    assert main_mod._txn_write(b"stable", b"local") is True
    assert (isolated / "config.local.json.txn").exists()


def test_txn_write_returns_false_on_failure(monkeypatch, isolated):
    """OSError on journal write -> _txn_write returns False (CORE-002)."""
    def boom(*a, **kw):
        raise OSError("simulated journal write failure")
    monkeypatch.setattr("os.replace", boom)
    assert main_mod._txn_write(b"stable", b"local") is False


def test_txn_recover_returns_none_when_no_journal(isolated):
    assert main_mod._txn_recover() == "NONE"


def test_txn_recover_returns_recovered_when_halves_committed(isolated, monkeypatch):
    (isolated / "config.local.json.txn").write_bytes(json.dumps({
        "stable": base64.b64encode(b'{"v":1}').decode("ascii"),
        "local": base64.b64encode(b'{"v":1,"local":true}').decode("ascii"),
    }).encode("utf-8"))
    assert main_mod._txn_recover() == "RECOVERED"
    assert (isolated / "config.json").read_bytes() == b'{"v":1}'
    assert (isolated / "config.local.json").read_bytes() == b'{"v":1,"local":true}'
    assert not (isolated / "config.local.json.txn").exists()


def test_txn_recover_returns_invalid_journal_on_malformed(isolated):
    (isolated / "config.local.json.txn").write_bytes(b"not json at all {")
    assert main_mod._txn_recover() == "INVALID_JOURNAL"
    assert not (isolated / "config.local.json.txn").exists()


def test_txn_recover_returns_pending_failed_on_io_error(isolated, monkeypatch):
    (isolated / "config.local.json.txn").write_bytes(json.dumps({
        "stable": base64.b64encode(b'stable').decode("ascii"),
        "local": base64.b64encode(b'local').decode("ascii"),
    }).encode("utf-8"))
    def boom(*a, **kw):
        raise OSError("simulated recovery I/O failure")
    monkeypatch.setattr(main_mod.config_store, "atomic_write_bytes", boom)
    assert main_mod._txn_recover() == "PENDING_FAILED"
    # journal is retained for next-startup repair
    assert (isolated / "config.local.json.txn").exists()


def test_load_config_blocks_when_txn_pending_failed(isolated, monkeypatch):
    (isolated / "config.local.json.txn").write_bytes(json.dumps({
        "stable": base64.b64encode(b'A').decode("ascii"),
        "local": base64.b64encode(b'B').decode("ascii"),
    }).encode("utf-8"))
    def boom(*a, **kw):
        raise OSError("simulated I/O")
    monkeypatch.setattr(main_mod.config_store, "atomic_write_bytes", boom)
    main_mod.load_config()
    # config_write_blocked armed -> load returned defaults, no live hybrid
    assert main_mod.config_write_blocked == "txn_unresolved"


def test_save_config_aborts_when_journal_unwritable(monkeypatch, isolated):
    """save_config must return False without writing either half when the
    transaction journal cannot be published (CORE-002 mandatory precondition)."""
    stable_path = isolated / "config.json"
    local_path = isolated / "config.local.json"
    stable_path.write_bytes(b'{"old":true}')
    local_path.write_bytes(b'{"old":true,"local":true}')
    cfg = {"toggles": {"target_exe": "HD-Player.exe"}}
    def boom(*a, **kw):
        raise OSError("simulated journal write failure")
    monkeypatch.setattr("os.replace", boom)
    assert main_mod.save_config(cfg) is False
    # both halves unchanged
    assert stable_path.read_bytes() == b'{"old":true}'
    assert local_path.read_bytes() == b'{"old":true,"local":true}'


def test_save_config_retains_journal_on_rollback_failure(monkeypatch, isolated):
    """When local write succeeds and stable write fails AND the rollback of
    the local half ALSO fails, the journal is retained so the next launch
    can attempt recovery from the durable candidate (CORE-002)."""
    stable_path = isolated / "config.json"
    local_path = isolated / "config.local.json"
    stable_path.write_bytes(b'{"old":true}')
    local_path.write_bytes(b'{"old":true,"local":true}')
    cfg = {"toggles": {"target_exe": "HD-Player.exe"}}
    # stable write fails
    original_atomic_write = main_mod.config_store.atomic_write
    call_state = {"count": 0}
    def selective(path, data, promote_bak=False):
        call_state["count"] += 1
        if "config.json" in path and call_state["count"] > 1:
            raise OSError("simulated stable write failure")
        return original_atomic_write(path, data, promote_bak=promote_bak)
    monkeypatch.setattr(main_mod.config_store, "atomic_write", selective)
    # rollback also fails
    original_atomic_write_bytes = main_mod.config_store.atomic_write_bytes
    def rollback_boom(path, data, promote_bak=False):
        raise OSError("simulated rollback failure")
    monkeypatch.setattr(main_mod.config_store, "atomic_write_bytes", rollback_boom)
    result = main_mod.save_config(cfg)
    assert result is False
    assert main_mod.config_write_blocked == "partial_commit"
    assert main_mod.local_write_blocked == "partial_commit"
    # journal retained for next-startup repair
    assert (isolated / "config.local.json.txn").exists()