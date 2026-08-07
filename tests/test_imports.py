"""Smoke tests: verify non-GUI modules import and py_compile clean."""

import py_compile
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent

SAFE_MODULES = [
    "ahk_builder",
    "champions",
    "digit_reader",
    "locales",
    "process_runner",
]

GUI_MODULES = [
    "capture",
    "window_ctl",
    "key_blocker",
    "single_instance",
    "theme",
    "accept",
    "autocontinue",
    "deathwatch",
    "ahk_generator",
    "tabs.bind_button",
]


def test_safe_modules_import():
    for name in SAFE_MODULES:
        module = __import__(name)
        assert module.__name__ == name, f"{name} failed to import"


def test_all_py_files_compile():
    root = BASE
    ok = 0
    failed = []
    for f in sorted(root.rglob("*.py")):
        if ".saipen" in f.parts or ".git" in f.parts:
            continue
        try:
            py_compile.compile(str(f), doraise=True)
            ok += 1
        except py_compile.PyCompileError:
            failed.append(str(f.relative_to(root)))
    assert not failed, f"{len(failed)} files fail compile:\n" + "\n".join(failed)
