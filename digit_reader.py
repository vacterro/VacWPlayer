import os

import cv2
import numpy as np

SAT_MAX = 60
VAL_MIN = 170
MIN_RUN_WIDTH = 3
MERGE_GAP = 2
# Digits sit at a fixed vertical position in this HUD element. Cropping a fixed
# band (rather than the mask's own row extent) survives frames where a banner
# overlaps and eats part of the glyph's mask (e.g. thin "1" losing its base).
GLYPH_ROWS = (0, 23)


def white_text_mask(bgr_crop):
    """Digits render near-white/cream. Thresholding on grayscale brightness alone
    also catches colored banner text (kill banners, pings) that's just as bright
    but saturated, so require low saturation too."""
    hsv = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]
    return (((sat < SAT_MAX) & (val > VAL_MIN)).astype(np.uint8)) * 255


def segment_columns(mask):
    col_sum = mask.sum(axis=0)
    cols_with_ink = col_sum > 0
    runs = []
    start = None
    for i, v in enumerate(cols_with_ink):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(cols_with_ink)))
    merged = []
    for r in runs:
        if merged and r[0] - merged[-1][1] <= MERGE_GAP:
            merged[-1] = (merged[-1][0], r[1])
        else:
            merged.append(list(r))
    return [tuple(r) for r in merged if r[1] - r[0] >= MIN_RUN_WIDTH]


def load_templates(digits_dir):
    """Load digit templates from directory. All-or-nothing: any discovered
    image that cannot be decoded rejects the whole candidate set so a corrupt
    resource never enters live state (T-CORE-011)."""
    templates = {}
    for fname in os.listdir(digits_dir):
        if fname.endswith(".png"):
            ch = os.path.splitext(fname)[0]
            img = cv2.imread(os.path.join(digits_dir, fname), cv2.IMREAD_GRAYSCALE)
            if img is None:
                raise ValueError("corrupt digit template: %s" % fname)
            templates[ch] = img
    return templates


def match_glyph(glyph_gray, templates):
    best_ch, best_score = None, -1.0
    for ch, tmpl in templates.items():
        resized = cv2.resize(glyph_gray, (tmpl.shape[1], tmpl.shape[0]))
        score = cv2.matchTemplate(resized, tmpl, cv2.TM_CCOEFF_NORMED)[0][0]
        if score > best_score:
            best_score, best_ch = score, ch
    return best_ch, best_score


def read_number(bgr_crop, templates, min_score=0.5):
    gray = cv2.cvtColor(bgr_crop, cv2.COLOR_BGR2GRAY)
    mask = white_text_mask(bgr_crop)
    runs = segment_columns(mask)
    if not runs:
        return None
    ry0, ry1 = GLYPH_ROWS
    digits = []
    for (x0, x1) in runs:
        cx0, cx1 = max(0, x0 - 1), min(gray.shape[1], x1 + 1)
        glyph = gray[ry0:ry1, cx0:cx1]
        ch, score = match_glyph(glyph, templates)
        if score < min_score:
            return None
        digits.append(ch)
    try:
        return int("".join(digits))
    except ValueError:
        return None


REGION = (955, 143, 1035, 170)
SAMPLES = [
    ("frame_0090_0057.4s.jpg", "42"),
    ("frame_0098_0062.5s.jpg", "37"),
    ("frame_0105_0067.0s.jpg", "32"),
    ("frame_0115_0073.4s.jpg", "26"),
    ("frame_0124_0079.2s.jpg", "20"),
    ("frame_0141_0090.0s.jpg", "9"),
    ("frame_0143_0091.3s.jpg", "8"),
    ("frame_0148_0094.5s.jpg", "5"),
    ("frame_0149_0095.1s.jpg", "4"),
    ("frame_0154_0098.3s.jpg", "1"),
]


def rebuild_templates(base):
    burst_dir = os.path.join(base, "templates", "burst_death")
    out_dir = os.path.join(base, "templates", "digits")
    os.makedirs(out_dir, exist_ok=True)
    x0, y0, x1, y1 = REGION
    ry0, ry1 = GLYPH_ROWS
    for fname, expected in SAMPLES:
        img = cv2.imread(os.path.join(burst_dir, fname))
        crop = img[y0:y1, x0:x1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mask = white_text_mask(crop)
        runs = segment_columns(mask)
        if len(runs) != len(expected):
            print(f"MISMATCH {fname}: expected {len(expected)} digits, found {len(runs)} runs -> {runs}")
            continue
        for (cx0, cx1), ch in zip(runs, expected):
            px0, px1 = max(0, cx0 - 1), min(gray.shape[1], cx1 + 1)
            glyph = gray[ry0:ry1, px0:px1]
            out_path = os.path.join(out_dir, f"{ch}.png")
            cv2.imwrite(out_path, glyph)
            print(f"saved digit '{ch}' from {fname} -> {out_path} size={glyph.shape[1]}x{glyph.shape[0]}")


if __name__ == "__main__":
    import sys

    base = os.path.dirname(__file__)
    if "--rebuild" in sys.argv:
        rebuild_templates(base)

    templates = load_templates(os.path.join(base, "templates", "digits"))
    print(f"loaded {len(templates)} templates: {sorted(templates.keys())}")

    burst_dir = os.path.join(base, "templates", "burst_death")
    ok = 0
    for fname, expected in SAMPLES:
        img = cv2.imread(os.path.join(burst_dir, fname))
        x0, y0, x1, y1 = REGION
        crop = img[y0:y1, x0:x1]
        result = read_number(crop, templates)
        expected_n = int(expected)
        status = "OK" if result == expected_n else "FAIL"
        ok += result == expected_n
        print(f"{status} {fname}: expected={expected_n} got={result}")
    print(f"{ok}/{len(SAMPLES)} correct")
