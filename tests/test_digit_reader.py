"""digit_reader unit tests: mask, column segmentation, glyph match, read_number.

Uses synthetic BGR crops so the tests need no real screen captures. The
functions are pure image logic - no win32, no window handles.
"""

import sys
from pathlib import Path

import cv2
import numpy as np

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

import digit_reader


def _dark_bgr(w=40, h=30):
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (40, 40, 40)  # dark background, low brightness
    return img


def _white_band(img, x0, x1, y0=3, y1=27):
    cv2.rectangle(img, (x0, y0), (x1, y1), (255, 255, 255), -1)
    return img


def _top_dim_shape(width):
    """23xW glyph: top rows bright (255), bottom rows dark (30). Every
    column carries bright ink, so the mask keeps the full width; the
    vertical step gives cv2.matchTemplate CCOEFF_NORMED a well-defined
    variance (a flat rectangle makes the normalized correlation undefined
    and every template scores ~1.0)."""
    tpl = np.zeros((23, width), np.uint8)
    tpl[:12, :] = 255
    tpl[12:, :] = 30
    return tpl


def _bottom_dim_shape(width):
    """23xW glyph: bottom rows bright (255), top rows dark (30) - the
    inverse of _top_dim_shape, structurally different, same full width."""
    tpl = np.zeros((23, width), np.uint8)
    tpl[12:, :] = 255
    tpl[:12, :] = 30
    return tpl


def _image_with_glyphs(glyphs, width, pad=4, margin=3):
    """Build a BGR crop containing `glyphs` side by side. Each glyph is
    pasted as its exact pattern array at a known column, so the column
    segmentation recovers runs equal to the glyph widths and match_glyph
    compares crop content to templates with no resize distortion."""
    total = margin + len(glyphs) * (width + pad)
    img = np.zeros((23, total, 3), np.uint8)
    img[:] = (40, 40, 40)
    for i, pattern in enumerate(glyphs):
        x0 = margin + i * (width + pad)
        img[:, x0:x0 + width] = pattern[:, :, None]  # grayscale on all channels
    return img


def test_white_text_mask_keeps_white_low_sat():
    img = _dark_bgr()
    _white_band(img, 5, 10)
    mask = digit_reader.white_text_mask(img)
    assert mask.max() == 255
    # the band columns should be ink
    assert (mask[:, 5:11].sum(axis=0) > 0).all()


def test_white_text_mask_rejects_colored_bright():
    # Bright but saturated (red) text must be masked out - that is the
    # whole point of the saturation gate (banner text vs digits).
    img = _dark_bgr()
    cv2.rectangle(img, (5, 3), (10, 26), (0, 0, 255), -1)  # bright red
    mask = digit_reader.white_text_mask(img)
    assert mask.max() == 0


def test_segment_columns_single_run():
    img = _dark_bgr()
    _white_band(img, 5, 10)
    runs = digit_reader.segment_columns(digit_reader.white_text_mask(img))
    assert len(runs) == 1
    assert runs[0] == (5, 11)


def test_segment_columns_two_runs_with_gap():
    img = _dark_bgr()
    _white_band(img, 3, 7)
    _white_band(img, 20, 24)
    runs = digit_reader.segment_columns(digit_reader.white_text_mask(img))
    assert len(runs) == 2
    assert runs[0] == (3, 8)
    assert runs[1] == (20, 25)


def test_segment_columns_merges_nearby_runs():
    # MERGE_GAP=2: a 1-col gap between runs merges them.
    img = _dark_bgr()
    _white_band(img, 3, 7)
    _white_band(img, 9, 12)
    runs = digit_reader.segment_columns(digit_reader.white_text_mask(img))
    assert len(runs) == 1
    assert runs[0] == (3, 13)


def test_segment_columns_filters_thin_noise():
    # MIN_RUN_WIDTH=3: a 1-2 px blip is noise, not a digit column.
    img = _dark_bgr()
    _white_band(img, 5, 6)
    runs = digit_reader.segment_columns(digit_reader.white_text_mask(img))
    assert runs == []


def test_segment_columns_empty_mask():
    img = _dark_bgr()
    assert digit_reader.segment_columns(digit_reader.white_text_mask(img)) == []


def test_match_glyph_picks_best_template():
    tpl = _top_dim_shape(6)
    glyph = _top_dim_shape(6)
    other = _bottom_dim_shape(6)
    ch, score = digit_reader.match_glyph(glyph, {"1": tpl, "2": other})
    assert ch == "1"
    assert score > 0.5


def test_read_number_synthetic_digits():
    # Two glyphs with structurally different brightness patterns -> two
    # runs -> two digits; patterns drive template match, not just width.
    img = _image_with_glyphs([_top_dim_shape(6), _bottom_dim_shape(6)], 6)
    templates = {
        "1": _top_dim_shape(6),
        "2": _bottom_dim_shape(6),
    }
    n = digit_reader.read_number(img, templates)
    assert n == 12


def test_read_number_none_when_no_digits():
    img = _dark_bgr()
    assert digit_reader.read_number(img, {"1": _top_dim_shape(6)}) is None


def test_read_number_respects_min_score():
    # Glyph too dissimilar to all templates -> None (min_score gate).
    img = _image_with_glyphs([_top_dim_shape(6)], 6)
    # Inverted template (dark top / bright bottom) never matches well.
    inv = 255 - _top_dim_shape(6)
    assert digit_reader.read_number(img, {"1": inv}, min_score=0.5) is None


def test_read_number_rejects_non_numeric():
    img = _image_with_glyphs([_top_dim_shape(6)], 6)
    # Templates force a non-digit char -> int() raises -> None.
    templates = {"x": _top_dim_shape(6)}
    assert digit_reader.read_number(img, templates) is None
