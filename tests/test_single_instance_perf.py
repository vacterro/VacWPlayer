"""PERF-007 regression: 1ms timer resolution must be SCOPED to a critical
section (begin on enter, end on exit - guaranteed even on exception) and must
NOT be requested for the whole process lifetime anymore."""

import ctypes

import pytest
import single_instance as si


class _FakeWinmm:
    def __init__(self, begin_rc=0):
        self.begin_rc = begin_rc
        self.begin = 0
        self.end = 0

    def timeBeginPeriod(self, ms):
        self.begin += 1
        return self.begin_rc

    def timeEndPeriod(self, ms):
        self.end += 1


def _patch(monkeypatch, winmm):
    monkeypatch.setattr(ctypes, "WinDLL",
                        lambda name, use_last_error=False: winmm)


def test_timer_resolution_balanced(monkeypatch):
    wm = _FakeWinmm()
    _patch(monkeypatch, wm)
    with si.timer_resolution(1):
        pass
    assert wm.begin == 1 and wm.end == 1


def test_timer_resolution_restores_on_exception(monkeypatch):
    wm = _FakeWinmm()
    _patch(monkeypatch, wm)
    with pytest.raises(ValueError):
        with si.timer_resolution(1):
            raise ValueError("boom")
    # Restored regardless of exception inside the block.
    assert wm.begin == 1 and wm.end == 1


def test_timer_resolution_skips_end_when_begin_rejected(monkeypatch):
    wm = _FakeWinmm(begin_rc=1)  # non-zero => OS rejected the request
    _patch(monkeypatch, wm)
    with si.timer_resolution(1):
        pass
    # Nothing was actually begun, so nothing should be ended.
    assert wm.begin == 1 and wm.end == 0
