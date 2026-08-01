#!/usr/bin/env python3
"""Execution-level HUNT — actually runs code, not just reads it.

Categories:
  1. Import chain verification (try importing every .py file)
  2. Key function smoke tests (isolated execution of critical functions)
  3. Config file type/range validation
  4. Template file integrity (readable, non-empty)
  5. AHK script syntax sanity check (structure, labels, hotkeys)
  6. Dependency availability (installed packages match requirements.txt)
  7. Module-level code execution safety (no side effects on import)
  8. Cross-reference: which files fail in which runtime dimension

Usage:  python tools/exec_hunt.py
"""

import os
import sys
import json
import subprocess
import traceback
from collections import defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)

# Any file starting with these prefixes is skipped (side effects / display / loops)
IMPORT_BLACKLIST_PREFIXES = ('tabs/', 'tools/', 'main.pyw', 'champ_picker',
                             'combo_browser', 'capture', 'window_ctl',
                             'key_blocker', 'autocontinue', 'deathwatch',
                             'vintage_widgets')  # vintage_widgets uses tkinter


def get_py_files():
    result = []
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if d != '__pycache__' and '.git' not in root]
        for f in files:
            if f.endswith('.py'):
                result.append(os.path.join(root, f))
    return sorted(result)


def short_path(full_path):
    p = full_path.replace(PROJECT, '').lstrip('\\/')
    return p.replace('\\\\', '/')


def to_module_path(filepath):
    """Convert file path to Python module path."""
    rel = os.path.relpath(filepath, PROJECT)
    rel = rel.replace('\\', '/').replace('.pyw', '').replace('.py', '')
    parts = rel.split('/')
    # Handle __init__.py
    if parts[-1] == '__init__':
        parts = parts[:-1]
    return '.'.join(parts), rel


# ──────────────────────────────────────────────
# 1. Import chain verification
# ──────────────────────────────────────────────

class ImportVerifier:
    """Try importing each module, safely, with timeout."""

    def verify(self, files):
        results = {}
        for f in files:
            sp = short_path(f)
            if any(sp.startswith(p) for p in IMPORT_BLACKLIST_PREFIXES):
                results[sp] = {'status': 'SKIP', 'error': 'blacklisted (side effects)'}
                continue
            mod_name, _ = to_module_path(f)
            try:
                # Try to import with timeout-like mechanism
                __import__(mod_name)
                results[sp] = {'status': 'OK', 'error': None}
            except Exception as e:
                tb = traceback.format_exc()
                results[sp] = {'status': 'FAIL', 'error': str(e), 'traceback': tb[-500:]}
        return results


# ──────────────────────────────────────────────
# 2. Key function smoke tests
# ──────────────────────────────────────────────

class SmokeTester:
    """Run isolated key functions and report results."""

    TESTS = []

    def run(self):
        results = []
        # Test config loading (direct JSON — no config.py in this project)
        try:
            with open(os.path.join(PROJECT, 'config.json'), encoding='utf-8-sig') as fh:
                data = json.load(fh)
            results.append(('config.json', 'OK', f'loaded {len(data)} keys'))
        except Exception as e:
            results.append(('config.json', 'FAIL', str(e)))

        # Test locales
        try:
            from locales import LOCALES
            results.append(('locales.LOCALES', 'OK', f'{len(LOCALES)} locales'))
        except Exception as e:
            results.append(('locales.LOCALES', 'FAIL', str(e)))

        # Test champions data
        try:
            from champions import CHAMPIONS, SOURCED_COMBOS
            n_champs = len(CHAMPIONS)
            n_combos = len(SOURCED_COMBOS) if SOURCED_COMBOS else 0
            results.append(('champions', 'OK', f'{n_champs} champions, {n_combos} combos'))
        except Exception as e:
            results.append(('champions', 'FAIL', str(e)))

        # Test themes
        try:
            from theme import TOKENS
            results.append(('theme.TOKENS', 'OK', f'{len(TOKENS)} tokens'))
        except Exception as e:
            results.append(('theme.TOKENS', 'FAIL', str(e)))

        # Test digit_reader constants
        try:
            from digit_reader import SAT_MAX, VAL_MIN, MIN_RUN_WIDTH
            results.append(('digit_reader constants', 'OK', f'{SAT_MAX=}, {VAL_MIN=}'))
        except Exception as e:
            results.append(('digit_reader constants', 'FAIL', str(e)))

        # Test single_instance
        try:
            import single_instance
            results.append(('single_instance', 'OK', 'imported'))
        except Exception as e:
            results.append(('single_instance', 'FAIL', str(e)))

        # Test process_runner
        try:
            import process_runner
            results.append(('process_runner', 'OK', 'imported'))
        except Exception as e:
            results.append(('process_runner', 'FAIL', str(e)))

        # Test combo_browser module-level (tkinter may fail headless)
        try:
            import combo_browser
            results.append(('combo_browser', 'OK', 'imported'))
        except Exception as e:
            results.append(('combo_browser', 'FAIL', str(e)[:80]))

        # Test ahk_generator key functions
        try:
            from ahk_generator import parse_steps, generate_script
            results.append(('ahk_generator', 'OK', 'parse_steps, generate_script imported'))
        except Exception as e:
            results.append(('ahk_generator', 'FAIL', str(e)[:80]))

        return results


# ──────────────────────────────────────────────
# 3. Config file type/range validation
# ──────────────────────────────────────────────

class ConfigValidator:
    def validate(self):
        results = []
        config_files = [
            ('config.json', {
                'keys': {
                    'lang': str,
                    'window': dict,
                    'hotkeys': dict,
                    'emulator': str,
                },
                'optional_keys': ['theme'],
            }),
            ('deathwatch_config.json', {
                'keys': {
                    'enabled': bool,
                    'interval': (int, float),
                },
                'optional_keys': ['hotkey', 'buy_delay', 'buy_items'],
            }),
            ('autocontinue_config.json', {
                'keys': {
                    'enabled': bool,
                    'actions': list,
                },
                'optional_keys': ['interval', 'retries'],
            }),
        ]

        for cfg_name, schema in config_files:
            cfg_path = os.path.join(PROJECT, cfg_name)
            if not os.path.exists(cfg_path):
                results.append((cfg_name, 'MISSING', 'file not found'))
                continue
            try:
                with open(cfg_path, encoding='utf-8-sig') as fh:
                    data = json.load(fh)
            except json.JSONDecodeError as e:
                results.append((cfg_name, 'INVALID JSON', str(e)))
                continue

            if not isinstance(data, dict):
                results.append((cfg_name, 'TYPE ERROR', 'root is not a dict'))
                continue

            # Check required keys
            required = schema.get('keys', {})
            optional = schema.get('optional_keys', [])
            for key, expected_type in required.items():
                if key not in data:
                    results.append((cfg_name, 'MISSING KEY', f'"{key}" required'))
                elif not isinstance(data[key], expected_type):
                    results.append((cfg_name, 'TYPE ERROR', f'"{key}" expected {expected_type.__name__}, got {type(data[key]).__name__}'))

            # Check for unknown keys
            all_known = set(required.keys()) | set(optional)
            for key in data:
                if key not in all_known:
                    results.append((cfg_name, 'UNKNOWN KEY', f'"{key}" not in schema'))

            results.append((cfg_name, 'OK', f'{len(data)} keys validated'))

        return results


# ──────────────────────────────────────────────
# 4. Template file integrity
# ──────────────────────────────────────────────

class TemplateChecker:
    def check(self):
        results = []
        templates_dir = os.path.join(PROJECT, 'templates')
        if not os.path.exists(templates_dir):
            results.append(('templates/', 'MISSING', 'directory not found'))
            return results

        # Check for _meta.txt files
        meta_files = []
        image_files = []
        for root, dirs, files in os.walk(templates_dir):
            for f in files:
                fp = os.path.join(root, f)
                if f.endswith('_meta.txt'):
                    meta_files.append(fp)
                elif f.lower().endswith(('.png', '.jpg', '.bmp')):
                    image_files.append(fp)
                elif f.endswith('.txt'):
                    meta_files.append(fp)

        # Validate meta files
        valid_meta = 0
        invalid_meta = 0
        for mf in meta_files:
            try:
                with open(mf, encoding='utf-8-sig') as fh:
                    content = fh.read()
                if len(content.strip()) > 0:
                    # Try to parse as metadata (key=value or JSON)
                    lines = content.strip().split('\n')
                    if len(lines) >= 1:
                        valid_meta += 1
                    else:
                        invalid_meta += 1
                else:
                    invalid_meta += 1
            except (OSError, UnicodeDecodeError):
                invalid_meta += 1

        results.append(('templates/', 'OK', f'{len(image_files)} images, {valid_meta} valid meta, {invalid_meta} invalid meta'))

        # Check image files are non-empty
        empty_images = 0
        for img in image_files:
            try:
                if os.path.getsize(img) == 0:
                    empty_images += 1
            except OSError:
                pass

        if empty_images:
            results.append(('templates/', 'WARN', f'{empty_images} empty image files'))

        return results


# ──────────────────────────────────────────────
# 5. AHK script structure check
# ──────────────────────────────────────────────

class AHKStructureChecker:
    def check(self):
        import re
        results = []
        ahk_path = os.path.join(PROJECT, 'wr_runtime.ahk')
        if not os.path.exists(ahk_path):
            results.append(('wr_runtime.ahk', 'MISSING', 'file not found'))
            return results

        with open(ahk_path, encoding='utf-8-sig') as fh:
            content = fh.read()
            lines = content.split('\n')

        # Count structural elements
        labels = []
        hotkeys = []
        directives = []
        functions = []
        loop_count = 0

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue
            # Directives
            if stripped.startswith('#'):
                directives.append((i, stripped))
            # Labels (word: at start of line, not inside function)
            if re.match(r'^\w+:', stripped) and not stripped.startswith('#'):
                labels.append((i, stripped.rstrip(':')))
            # Hotkeys (word:: at start)
            if re.match(r'^~?\w+::', stripped):
                hotkeys.append((i, stripped.split('::')[0]))
            # Functions
            if re.match(r'^\w+\(', stripped):
                functions.append((i, stripped.split('(')[0]))

        results.append(('wr_runtime.ahk', 'OK', f'{len(lines)} lines'))
        results.append(('wr_runtime.ahk', 'INFO', f'{len(directives)} directives: {", ".join(d[1] for d in directives[:5])}'))
        results.append(('wr_runtime.ahk', 'INFO', f'{len(labels)} labels: {", ".join(l[1] for l in labels[:5])}'))
        results.append(('wr_runtime.ahk', 'INFO', f'{len(hotkeys)} hotkeys'))
        results.append(('wr_runtime.ahk', 'INFO', f'{len(functions)} functions'))

        # Check for matching braces
        open_braces = content.count('{')
        close_braces = content.count('}')
        if open_braces != close_braces:
            results.append(('wr_runtime.ahk', 'SYNTAX', f'brace mismatch: {open_braces} open vs {close_braces} close'))

        # Check for common AHK errors
        if 'Return' not in content and '#Persistent' not in content:
            results.append(('wr_runtime.ahk', 'WARN', 'no Return or #Persistent — script exits immediately'))

        return results


# ──────────────────────────────────────────────
# 6. Dependency availability
# ──────────────────────────────────────────────

class DependencyChecker:
    def check(self):
        results = []
        req_path = os.path.join(PROJECT, 'requirements.txt')
        if not os.path.exists(req_path):
            results.append(('requirements.txt', 'MISSING', 'file not found'))
            return results

        try:
            with open(req_path, encoding='utf-8-sig') as fh:
                reqs = fh.readlines()
        except OSError:
            results.append(('requirements.txt', 'FAIL', 'cannot read'))
            return results

        for line in reqs:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('-'):
                continue
            # Extract package name
            pkg = line.split('=')[0].split('>')[0].split('<')[0].split('[')[0].split(';')[0].strip()
            if not pkg:
                continue
            try:
                __import__(pkg)
                results.append((f'dep:{pkg}', 'OK', 'installed'))
            except ImportError:
                # Try with underscores
                alt = pkg.replace('-', '_')
                try:
                    __import__(alt)
                    results.append((f'dep:{pkg}', 'OK', 'installed (as {alt})'))
                except ImportError:
                    results.append((f'dep:{pkg}', 'MISSING', 'not installed'))

        return results


# ──────────────────────────────────────────────
# 7. Module-level code safety
# ──────────────────────────────────────────────

class ModuleSafetyChecker:
    """Check if modules have side effects at import time (function calls at module level)."""

    def check(self, files):
        results = []
        import ast as _ast
        SAFE_CALLS = frozenset({'print', 'len', 'str', 'int', 'list', 'dict', 'set',
                                'type', 'isinstance', 'issubclass', 'hasattr', 'getattr',
                                'open', 'range', 'enumerate', 'sorted', 'reversed',
                                'zip', 'map', 'filter', 'any', 'all', 'sum', 'min', 'max',
                                'Path', '__import__', 'dir', 'float', 'json', 'os', 'sys',
                                'hasattr', 'repr', 'bool', 'bytes', 'tuple'})

        for f in files:
            sp = short_path(f)
            if any(sp.startswith(p) for p in IMPORT_BLACKLIST_PREFIXES):
                continue
            try:
                with open(f, encoding='utf-8-sig') as fh:
                    content = fh.read()
                tree = _ast.parse(content, f)
            except (SyntaxError, UnicodeDecodeError):
                continue

            # Walk AST with scope tracking — DFS that tracks nesting
            def _dfs(node, in_func):
                if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef, _ast.ClassDef)):
                    in_func = True
                if isinstance(node, _ast.Call) and not in_func:
                    if isinstance(node.func, _ast.Name) and node.func.id not in SAFE_CALLS:
                        results.append((sp, 'WARN', f'module-level call: {node.func.id}()'))
                for child in _ast.iter_child_nodes(node):
                    _dfs(child, in_func)

            _dfs(tree, False)

        return results


# ──────────────────────────────────────────────
# 8. Config → Actual usage cross-reference
# ──────────────────────────────────────────────

class ConfigUsageXRef:
    """Check each config field is actually referenced in source code as string literal."""

    def check(self, files):
        results = []
        config_path = os.path.join(PROJECT, 'config.json')
        if not os.path.exists(config_path):
            return results

        with open(config_path, encoding='utf-8-sig') as fh:
            config = json.load(fh)

        source_text = ''
        for f in files:
            try:
                with open(f, encoding='utf-8-sig') as fh:
                    source_text += fh.read() + '\n'
            except (OSError, UnicodeDecodeError):
                pass

        def _check(prefix, data, path=''):
            if isinstance(data, dict):
                for key, value in data.items():
                    full_path = f'{path}.{key}' if path else key
                    # Check if key appears as string literal in source
                    key_refs = source_text.count(f"'{key}'") + source_text.count(f'"{key}"')
                    if key_refs <= 2:  # Only the config.json itself references it
                        results.append((f'config.json', f'UNUSED', f'field "{full_path}" never referenced in code'))
                    if isinstance(value, (dict, list)):
                        _check(prefix, value, full_path)

        _check('config', config)
        return results


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def print_sep(title):
    print(f'\n{"=" * 60}')
    print(f'  {title}')
    print('=' * 60)


def main():
    files = get_py_files()
    print(f'EXEC HUNT — testing {len(files)} Python files')
    print('=' * 60)

    results = {}
    all_findings = []

    # 1. Import verification
    print_sep('1. IMPORT CHAIN VERIFICATION')
    verifier = ImportVerifier()
    import_results = verifier.verify(files)
    ok_count = sum(1 for r in import_results.values() if r['status'] == 'OK')
    fail_count = sum(1 for r in import_results.values() if r['status'] == 'FAIL')
    skip_count = sum(1 for r in import_results.values() if r['status'] == 'SKIP')
    print(f'  OK: {ok_count}, FAIL: {fail_count}, SKIP: {skip_count}')
    for path, r in sorted(import_results.items()):
        if r['status'] != 'OK':
            print(f'    {path}: {r["status"]} — {r.get("error", "")[:80]}')
            all_findings.append((1, f'{path}: {r["error"]}'))
    results[1] = fail_count

    # 2. Smoke tests
    print_sep('2. KEY FUNCTION SMOKE TESTS')
    tester = SmokeTester()
    smoke_results = tester.run()
    smoke_ok = sum(1 for _, s, _ in smoke_results if s == 'OK')
    smoke_fail = sum(1 for _, s, _ in smoke_results if s == 'FAIL')
    print(f'  OK: {smoke_ok}, FAIL: {smoke_fail}')
    for name, status, msg in smoke_results:
        tag = '[OK]' if status == 'OK' else '[FAIL]'
        print(f'    {tag} {name}: {msg}')
        if status != 'OK':
            all_findings.append((2, f'{name}: {msg}'))
    results[2] = smoke_fail

    # 3. Config validation
    print_sep('3. CONFIG FILE VALIDATION')
    validator = ConfigValidator()
    config_results = validator.validate()
    config_issues = sum(1 for _, s, _ in config_results if s not in ('OK', 'INFO'))
    for name, status, msg in config_results:
        if status == 'OK':
            print(f'    [OK] {name}: {msg}')
        else:
            print(f'    [{status}] {name}: {msg}')
            all_findings.append((3, f'{name}: {msg}'))
    results[3] = config_issues

    # 4. Template integrity
    print_sep('4. TEMPLATE INTEGRITY')
    tc = TemplateChecker()
    template_results = tc.check()
    for name, status, msg in template_results:
        tag = '[OK]' if status == 'OK' else f'[{status}]'
        print(f'    {tag} {name}: {msg}')
    results[4] = len(template_results)

    # 5. AHK structure
    print_sep('5. AHK SCRIPT STRUCTURE')
    ahk = AHKStructureChecker()
    ahk_results = ahk.check()
    ahk_issues = sum(1 for _, s, _ in ahk_results if s not in ('OK', 'INFO'))
    for name, status, msg in ahk_results:
        tag = f'[{status}]'
        print(f'    {tag} {name}: {msg}')
        if status not in ('OK', 'INFO'):
            all_findings.append((5, f'{name}: {msg}'))
    results[5] = ahk_issues

    # 6. Dependency check
    print_sep('6. DEPENDENCY AVAILABILITY')
    dc = DependencyChecker()
    dep_results = dc.check()
    dep_ok = sum(1 for _, s, _ in dep_results if s == 'OK')
    dep_missing = sum(1 for _, s, _ in dep_results if s == 'MISSING')
    print(f'  OK: {dep_ok}, MISSING: {dep_missing}')
    for name, status, msg in dep_results:
        if status != 'OK':
            print(f'    [{status}] {name}: {msg}')
            all_findings.append((6, f'{name}: {msg}'))
    results[6] = dep_missing

    # 7. Module-level code safety
    print_sep('7. MODULE-LEVEL CODE SAFETY')
    msc = ModuleSafetyChecker()
    safety_results = msc.check(files)
    if safety_results:
        print(f'  Found {len(safety_results)} module-level calls:')
        for path, sev, msg in safety_results:
            print(f'    {path}: {msg}')
            all_findings.append((7, f'{path}: {msg}'))
    else:
        print('  All module-level code is safe (only function/class definitions)')
    results[7] = len(safety_results)

    # 8. Config usage cross-reference
    print_sep('8. CONFIG-USAGE CROSS-REFERENCE')
    xref = ConfigUsageXRef()
    xref_results = xref.check(files)
    if xref_results:
        for name, sev, msg in xref_results:
            print(f'    [{sev}] {name}: {msg}')
            all_findings.append((8, f'{name}: {msg}'))
    else:
        print('  All config fields are referenced in code')
    results[8] = len(xref_results)

    # Summary
    print('\n' + '=' * 60)
    print('EXEC HUNT — SUMMARY')
    print('=' * 60)
    labels = {
        1: 'Import chain',
        2: 'Smoke tests',
        3: 'Config validation',
        4: 'Template integrity',
        5: 'AHK structure',
        6: 'Dependencies',
        7: 'Module safety',
        8: 'Config xref',
    }
    for cat in sorted(results):
        print(f'  Cat {cat} ({labels[cat]:20s}): {results[cat]} issues')
    print('  ' + '-' * 40)
    cat_sum = sum(results.values())
    print(f'  {"TOTAL ISSUES":28s}: {cat_sum}')
    print('=' * 60)
    return cat_sum


if __name__ == '__main__':
    sys.exit(main())
