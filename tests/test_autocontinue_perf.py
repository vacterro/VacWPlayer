"""PERF-004 regression for autocontinue: the BACKGROUND (occlusion-safe) scan
path must take ONE PrintWindow, then crop each region FIRST and convert only the
crop to gray - never a full-frame BGR->gray conversion. Validated by feeding a
synthetic BGRA frame and asserting the small region is detected and clicked."""

import cv2
import numpy as np
import autocontinue as ac


def test_scan_background_crops_before_gray(monkeypatch):
    # 10x10 synthetic BGRA frame; a distinctive block at rows 2:5, cols 3:6.
    full = np.zeros((10, 10, 4), dtype=np.uint8)
    full[2:5, 3:6, 0:3] = 200
    monkeypatch.setattr(ac.capture, "grab_rgba", lambda hwnd: full)
    monkeypatch.setattr(ac.capture, "is_foreground", lambda hwnd: False)
    monkeypatch.setattr(ac.capture, "get_client_size", lambda hwnd: (10, 10))

    clicked = []
    monkeypatch.setattr(ac.window_ctl, "click_at",
                        lambda *a, **k: clicked.append(a))

    region = [3, 2, 6, 5]  # x0, y0, x1, y1 -> crops full[2:5, 3:6]
    tmpl = cv2.cvtColor(full[2:5, 3:6, :3], cv2.COLOR_BGR2GRAY)
    buttons = [{"name": "cont", "region": region, "threshold": 0.5, "tmpl": tmpl}]
    targets = (buttons, ac.group_by_region(buttons))
    cfg = {"window_title": "x"}

    assert ac._scan(123, cfg, targets) is True
    assert clicked  # region center was clicked
    # center of region [3,2,6,5]
    assert clicked[0][1] == 4 and clicked[0][2] == 3
