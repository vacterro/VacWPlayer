"""PERF-004 regression: region-only capture must crop FIRST and convert only the
crop, never materializing a full-frame BGR/gray copy. Pure-transform tests
(monkeypatched GDI source), no real window required."""

import numpy as np
import capture


def _fake_bgra(h=8, w=6):
    """Synthetic 4-channel BGRA frame: B=10, G=20, R=30, A=255."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, 0] = 10
    arr[:, :, 1] = 20
    arr[:, :, 2] = 30
    arr[:, :, 3] = 255
    return arr


def test_grab_rgba_returns_four_channels(monkeypatch):
    monkeypatch.setattr(capture, "_printwindow_bgra", lambda hwnd: _fake_bgra(8, 6))
    img = capture.grab_rgba(123)
    assert img.shape == (8, 6, 4)
    assert img.dtype == np.uint8


def test_grab_drops_alpha_to_bgr(monkeypatch):
    monkeypatch.setattr(capture, "_printwindow_bgra", lambda hwnd: _fake_bgra(8, 6))
    img = capture.grab(123)
    assert img.shape == (8, 6, 3)
    # BGR order preserved from the synthetic BGRA source.
    assert tuple(img[0, 0]) == (10, 20, 30)
    assert img.flags["C_CONTIGUOUS"]


def test_grab_client_region_crops_first(monkeypatch):
    monkeypatch.setattr(capture, "_printwindow_bgra", lambda hwnd: _fake_bgra(20, 20))
    region = [2, 3, 7, 9]  # x0, y0, x1, y1
    img = capture.grab_client_region(123, region)
    # crop height = 9-3 = 6, width = 7-2 = 5
    assert img.shape == (6, 5, 3)
    assert tuple(img[0, 0]) == (10, 20, 30)
    assert img.flags["C_CONTIGUOUS"]
