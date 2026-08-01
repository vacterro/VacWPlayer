"""Locale coverage tests: every language bundle must match EN key set,
tr() falls back to EN then raw key, set_lang guards invalid codes."""

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

import locales  # noqa: E402


def _flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = prefix + k if not prefix else prefix + "." + k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def test_en_ru_key_parity():
    en = set(_flatten(locales.LOCALES["en"]))
    ru = set(_flatten(locales.LOCALES["ru"]))
    assert en == ru, (
        f"en/ru key mismatch:\n"
        f"  only in en: {sorted(en - ru)}\n"
        f"  only in ru: {sorted(ru - en)}"
    )


def test_all_bundles_key_parity_with_en():
    en = set(_flatten(locales.LOCALES["en"]))
    for code in locales.Locale.languages():
        bundle = locales.LOCALES.get(code, {})
        if not bundle:
            continue
        keys = set(_flatten(bundle))
        missing = en - keys
        assert not missing, f"{code}: missing {len(missing)} keys: {sorted(missing)[:20]}"


def test_tr_falls_back_to_en():
    locales.Locale.set_lang("ded")
    assert locales.Locale.tr("stopped")  # any key resolves non-empty
    assert locales.Locale.tr("tab_main")  # et/ded know tab keys
    missing = "no_such_key_zzz"
    assert locales.Locale.tr(missing) == missing
    assert locales.Locale.tr(missing, fallback="fb") == "fb"


def test_slots_nested_resolution():
    locales.Locale.set_lang("en")
    assert locales.Locale.tr("slots.top") == "Top"
    locales.Locale.set_lang("ru")
    assert locales.Locale.tr("slots.base") == "База"
    locales.Locale.set_lang("et")
    assert locales.Locale.tr("slots.top") == "Ülemine"


def test_set_lang_invalid_falls_back():
    locales.Locale.set_lang("xx-not-a-lang")
    assert locales.Locale.current() == "en"


def test_bundle_files_load():
    loc_dir = BASE / "locales"
    files = {f.stem for f in loc_dir.glob("*.json")}
    assert {"en", "ru", "et", "ded"}.issubset(files)
    for f in loc_dir.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        assert isinstance(data, dict) and data, f"{f.name} empty/invalid"
