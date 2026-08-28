"""ahk_generator unit tests (CORE-001 pinned-handle force-kill defense)."""

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import ahk_generator as ag


class _StubHandle:
    def __init__(self, ownership="owned", terminate_raises=None, wait_rc=0):
        self.ownership = ownership
        self.terminate_raises = terminate_raises
        self.wait_rc = wait_rc
        self.terminated = False
        self.closed = False

    def CloseHandle(self):
        self.closed = True


def _install_handle_ownership(monkeypatch, ownership, wait_rc=0):
    from types import SimpleNamespace
    def _terminate(h, c):
        h.terminated = True
        if h.terminate_raises:
            raise h.terminate_raises
    monkeypatch.setattr(ag, "_pid_alive", lambda pid: True)
    monkeypatch.setattr(ag, "win32api", SimpleNamespace(
        OpenProcess=lambda *a, **kw: _StubHandle(ownership=ownership),
        CloseHandle=lambda h: h.CloseHandle(),
        TerminateProcess=_terminate,
    ))
    monkeypatch.setattr(ag, "win32event", SimpleNamespace(
        WaitForSingleObject=lambda h, t: wait_rc,
    ))
    monkeypatch.setattr(ag, "_handle_ownership", lambda h: h.ownership)


def test_force_kill_pinned_handle_owned_succeeds(monkeypatch):
    """Pinned handle re-verified as owned -> terminated, returns True."""
    _install_handle_ownership(monkeypatch, "owned")
    assert ag._force_kill_ahk_processes([1234]) is True


def test_force_kill_pinned_handle_foreign_skipped(monkeypatch):
    """PID reused by foreign process -> NOT terminated, NOT counted as dead."""
    _install_handle_ownership(monkeypatch, "foreign")
    assert ag._force_kill_ahk_processes([1234]) is True
    # foreign must be a no-op, not a destructive call


def test_force_kill_pinned_handle_unknown_fails(monkeypatch):
    """Unknown ownership -> not terminated, returns False."""
    _install_handle_ownership(monkeypatch, "unknown")
    assert ag._force_kill_ahk_processes([1234]) is False


def test_force_kill_openprocess_fails_no_handle(monkeypatch):
    """OpenProcess denial -> returns False (cannot prove exit)."""
    from types import SimpleNamespace
    import pywintypes
    monkeypatch.setattr(ag, "_pid_alive", lambda pid: True)

    def deny(*a, **kw):
        raise pywintypes.error(5, "OpenProcess", "access denied")
    monkeypatch.setattr(ag, "win32api", SimpleNamespace(OpenProcess=deny))
    assert ag._force_kill_ahk_processes([1234]) is False


def test_force_kill_wait_timeout_returns_false(monkeypatch):
    """WaitForSingleObject timeout -> handle is closed but not considered dead."""
    _install_handle_ownership(monkeypatch, "owned", wait_rc=0x00000102)
    assert ag._force_kill_ahk_processes([1234]) is False