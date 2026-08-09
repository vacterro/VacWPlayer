"""meta_hunt health metrics are computed from live sources, never hardcoded
(T-128). The old static recommendations block claimed config.json carried
orphan fields "lang", "window" - "lang" is consumed by config_store.py and
"window" is not even a config key. These tests pin the computed behaviour."""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if str(BASE / "tools") not in sys.path:
    sys.path.insert(0, str(BASE / "tools"))

import meta_hunt
from _common import get_py_files


def test_orphan_config_fields_lang_not_orphan():
    """config.json's real keys are referenced by the code - "lang" included."""
    orphans = meta_hunt.find_orphan_config_fields(get_py_files())
    assert isinstance(orphans, list)
    assert "lang" not in orphans
    # the old hardcoded claim named "window", which is not even a key
    assert "window" not in orphans


def test_ast_health_signals_computed(tmp_path):
    src = tmp_path / "sample.py"
    src.write_text(
        "import logging\n"
        "def typed(x: int) -> int:\n"
        "    return x\n"
        "def untyped(x):\n"
        "    try:\n"
        "        return 1 // x\n"
        "    except ZeroDivisionError:\n"
        "        pass\n"
        "def branchy(x):\n"
        "    if x and (x > 1 or x < 0):\n"
        "        for i in range(x):\n"
        "            while i:\n"
        "                break\n"
        "        else:\n"
        "            pass\n"
        "    return x\n",
        encoding="utf-8",
    )
    h = meta_hunt._ast_health_signals([str(src)])
    assert h["total_funcs"] == 3
    assert h["typed_funcs"] == 1
    assert h["imports_logging"] is True
    assert h["empty_excepts"] == 1
    assert h["max_complexity"] >= 4


def test_ast_health_signals_no_logging(tmp_path):
    src = tmp_path / "sample.py"
    src.write_text("def f():\n    return 1\n", encoding="utf-8")
    h = meta_hunt._ast_health_signals([str(src)])
    assert h["imports_logging"] is False
    assert h["typed_pct"] == 0.0
