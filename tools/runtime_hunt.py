#!/usr/bin/env python3
"""Runtime-adjacent HUNT scanner — 8 categories.

Categories:
  1. Config field usage trace (read/write per field across files)
  2. AHK script static analysis (wr_runtime.ahk)
  3. Subprocess/thread lifecycle tracking
  4. Startup flow path (main.pyw -> tab init)
  5. Resource cleanup: atexit, __del__, context managers
  6. Cross-file dead import analysis (imported but never referenced)
  7. Logging coverage (try/except blocks with vs without logging)
  8. Error message quality audit

Usage:  python tools/runtime_hunt.py
"""

import ast
import json as json_lib
import os
import sys
import re
from collections import defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_py_files():
    result = []
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if d != '__pycache__']
        for f in files:
            if f.endswith('.py'):
                result.append(os.path.join(root, f))
    return sorted(result)


def short_path(full_path):
    p = full_path.replace(PROJECT, '').lstrip('\\/')
    return p.replace('\\\\', '/')


def parse_file(f):
    try:
        with open(f, encoding='utf-8-sig') as fh:
            return ast.parse(fh.read(), f)
    except (SyntaxError, UnicodeDecodeError) as e:
        return None


# ──────────────────────────────────────────────
# 1. Config field usage trace
# ──────────────────────────────────────────────

class ConfigFieldTracer:
    """Trace which config.json fields are read/written across the project."""

    CONFIG_FILES = ['config.json', 'deathwatch_config.json', 'autocontinue_config.json']
    CONFIG_VARS = {'config', 'cfg', 'conf', 'data', 'settings'}
    # Also match self.config, self.cfg patterns
    CONFIG_ATTRS = {'config', 'cfg', 'conf'}

    def analyze(self, files):
        config_fields = {}

        for cfg_name in self.CONFIG_FILES:
            cfg_path = os.path.join(PROJECT, cfg_name)
            fields = set()
            if os.path.exists(cfg_path):
                try:
                    with open(cfg_path, encoding='utf-8-sig') as fh:
                        data = json_lib.load(fh)
                    if isinstance(data, dict):
                        fields = set(data.keys())
                except (json_lib.JSONDecodeError, OSError):
                    pass
            config_fields[cfg_name] = fields

        field_usage = defaultdict(lambda: {'reads': [], 'writes': []})

        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue
            path = short_path(f)

            def _is_config_obj(node):
                """Check if node references a config-like variable."""
                if isinstance(node, ast.Name) and node.id in self.CONFIG_VARS:
                    return True
                if isinstance(node, ast.Attribute):
                    if isinstance(node.value, ast.Name) and node.value.id == 'self':
                        return node.attr in self.CONFIG_ATTRS
                return False

            for node in ast.walk(tree):
                # Subscript access: config['key'] or cfg.get('key')
                if isinstance(node, ast.Subscript):
                    if _is_config_obj(node.value):
                        if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                            key = node.slice.value
                            if isinstance(node.ctx, ast.Store):
                                field_usage[key]['writes'].append((path, node.lineno))
                            else:
                                field_usage[key]['reads'].append((path, node.lineno))

                # .get() .pop() calls on config objects
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr in ('get', 'pop', '__getitem__', '__setitem__'):
                            if _is_config_obj(node.func.value):
                                for arg in node.args:
                                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                        if node.func.attr in ('__setitem__',):
                                            field_usage[arg.value]['writes'].append((path, node.lineno))
                                        else:
                                            field_usage[arg.value]['reads'].append((path, node.lineno))

        return config_fields, field_usage


# ──────────────────────────────────────────────
# 2. AHK script static analysis
# ──────────────────────────────────────────────

class AHKAnalyzer:
    """Analyze wr_runtime.ahk for issues."""

    def analyze(self):
        ahk_path = os.path.join(PROJECT, 'wr_runtime.ahk')
        if not os.path.exists(ahk_path):
            return None, []

        with open(ahk_path, encoding='utf-8-sig') as fh:
            lines = fh.readlines()

        issues = []
        total_lines = len(lines)

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(';'):
                continue
            # Hardcoded drive paths: C:\something
            if re.search(r"[A-Za-z]:\\(?!n)", line):
                issues.append((i, 'HIGH', f'Hardcoded path: {stripped[:60]}'))
            # Comments containing TODO/FIXME
            if re.search(r'(TODO|FIXME|HACK|XXX)', stripped, re.I):
                issues.append((i, 'INFO', f'Marker in AHK: {stripped[:60]}'))
            # Sleep with large values
            m = re.search(r'Sleep,\s*(\d+)', stripped)
            if m and int(m.group(1)) > 5000:
                issues.append((i, 'LOW', f'Long Sleep({m.group(1)}ms)'))
            # Potential infinite loop
            if re.match(r'Loop\s*$', stripped):
                issues.append((i, 'LOW', 'Unconditional Loop'))

        has_persistent = any('#Persistent' in l for l in lines)
        has_onerror = any('OnError' in l or 'Try' in l for l in lines)

        metadata = {
            'total_lines': total_lines,
            'has_persistent': has_persistent,
            'has_error_handling': has_onerror,
            'num_labels': sum(1 for l in lines if re.match(r'^\w+:', l) and not l.strip().startswith(';')),
            'num_hotkeys': sum(1 for l in lines if re.match(r'^~?\w+::', l)),
        }

        issues.append((1, 'INFO', f'AHK script: {total_lines} lines, {metadata["num_labels"]} labels, {metadata["num_hotkeys"]} hotkeys'))
        if not has_persistent:
            issues.append((1, 'HIGH', 'Missing #Persistent - script may terminate early'))
        if not has_onerror:
            issues.append((1, 'LOW', 'No error handling (Try/OnError) in AHK'))

        return metadata, issues


# ──────────────────────────────────────────────
# 3. Subprocess/thread lifecycle
# ──────────────────────────────────────────────

class ProcessLifecycleAnalyzer:
    def analyze(self, files):
        findings = []

        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue
            path = short_path(f)

            in_func = '<module>'
            in_class = None

            class LifecycleVisitor(ast.NodeVisitor):
                def visit_FunctionDef(self_, n):
                    nonlocal in_func, in_class
                    old_func = in_func
                    in_func = n.name
                    self_.generic_visit(n)
                    in_func = old_func

                def visit_ClassDef(self_, n):
                    nonlocal in_class
                    old_cls = in_class
                    in_class = n.name
                    self_.generic_visit(n)
                    in_class = old_cls

                def visit_Call(self_, n):
                    nonlocal in_func, in_class
                    is_popen = False
                    if isinstance(n.func, ast.Name) and n.func.id == 'Popen':
                        is_popen = True
                    elif isinstance(n.func, ast.Attribute):
                        if isinstance(n.func.value, ast.Name) and n.func.value.id == 'subprocess':
                            if n.func.attr == 'Popen':
                                is_popen = True
                    if is_popen:
                        findings.append((path, n.lineno, 'INFO',
                                         f'Popen in {in_class+":" if in_class else ""}{in_func}()'))

                    # Thread(target=...).start()
                    if isinstance(n.func, ast.Attribute) and n.func.attr == 'start':
                        if isinstance(n.func.value, ast.Call):
                            call = n.func.value
                            if isinstance(call.func, ast.Name) and call.func.id == 'Thread':
                                findings.append((path, n.lineno, 'INFO',
                                                 f'Thread.start() in {in_class+":" if in_class else ""}{in_func}()'))

                    self_.generic_visit(n)

            LifecycleVisitor().visit(tree)

        return findings


# ──────────────────────────────────────────────
# 4. Startup flow path
# ──────────────────────────────────────────────

class StartupFlowAnalyzer:
    def analyze(self, files):
        imports = {}

        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue
            mods = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        mods.append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        full = node.module
                        if node.level > 0:
                            prefix = '.' * node.level
                            full = prefix + full if full else prefix
                        mods.append(full)
            imports[short_path(f)] = mods

        main_path = short_path(os.path.join(PROJECT, 'main.pyw'))

        chain = []
        visited = set()

        def trace(file_key, depth=0):
            if file_key in visited or depth > 10:
                return
            visited.add(file_key)
            chain.append(file_key)
            for mod in imports.get(file_key, []):
                parts = mod.lstrip('.').split('.')
                for py_file in files:
                    sp = short_path(py_file)
                    mod_path = '/'.join(parts) + '.py'
                    if sp.endswith(mod_path) or (parts and sp.replace('.py', '').replace('/', '.').endswith(parts[-1])):
                        if sp not in visited:
                            trace(sp, depth + 1)
                            break

        trace(main_path)
        return chain, imports


# ──────────────────────────────────────────────
# 5. Resource cleanup
# ──────────────────────────────────────────────

class ResourceCleanupAnalyzer:
    def analyze(self, files):
        findings = []
        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue
            path = short_path(f)

            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        if (isinstance(node.func.value, ast.Name)
                                and node.func.value.id == 'atexit'
                                and node.func.attr == 'register'):
                            findings.append((path, node.lineno, 'INFO', 'atexit.register() - cleanup registered'))

                        if node.func.attr in ('destroy', 'quit'):
                            findings.append((path, node.lineno, 'LOW', f'Cleanup: .{node.func.attr}() call'))

                if isinstance(node, ast.FunctionDef) and node.name == '__del__':
                    findings.append((path, node.lineno, 'LOW', '__del__() defined - cleanup path'))

                if isinstance(node, ast.With):
                    for item in node.items:
                        ctx = item.context_expr
                        if isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Name):
                            if ctx.func.id in ('open', 'lock', 'Lock'):
                                findings.append((path, node.lineno, 'INFO', f'with {ctx.func.id}() - resource guarded'))

        return findings


# ──────────────────────────────────────────────
# 6. Cross-file dead import analysis
# ──────────────────────────────────────────────

class DeadImportAnalyzer:
    def analyze(self, files):
        report = defaultdict(list)

        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue
            path = short_path(f)

            imported_names = {}
            used_names = set()
            local_defs = set()

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        name = alias.asname or alias.name.split('.')[0]
                        imported_names[name] = (node.lineno, alias.name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        name = alias.asname or alias.name
                        imported_names[name] = (node.lineno, f'{node.module or "."}.{alias.name}')

                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    local_defs.add(node.name)
                if isinstance(node, ast.ClassDef):
                    local_defs.add(node.name)

                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    used_names.add(node.id)

            for name, (lineno, source) in imported_names.items():
                if name not in used_names and name not in local_defs:
                    report[path].append((lineno, name, source))

        return report


# ──────────────────────────────────────────────
# 7. Logging coverage
# ──────────────────────────────────────────────

class LoggingCoverageAnalyzer:
    def analyze(self, files):
        findings = []
        cov = {'with_logging': 0, 'silent_pass': 0, 'active_no_log': 0}
        has_logging = False

        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue
            path = short_path(f)

            file_has_logging = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == 'logging':
                            file_has_logging = True
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name == 'logging':
                            file_has_logging = True
            if file_has_logging:
                has_logging = True

            for node in ast.walk(tree):
                if isinstance(node, ast.Try):
                    for handler in node.handlers:
                        is_tk = False
                        if isinstance(handler.type, ast.Attribute):
                            if isinstance(handler.type.value, ast.Name) and handler.type.value.id == 'tk':
                                is_tk = True
                        if is_tk:
                            continue

                        has_log = any(
                            isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                            and isinstance(s.value.func, ast.Attribute)
                            and 'log' in s.value.func.attr.lower()
                            for s in (handler.body or [])
                        )
                        has_msg = any(
                            isinstance(s, ast.Expr) and isinstance(s.value, ast.Call)
                            and isinstance(s.value.func, ast.Name)
                            and s.value.func.id in ('print', 'warn')
                            for s in (handler.body or [])
                        )

                        is_empty = all(isinstance(s, ast.Pass) for s in (handler.body or []))

                        if is_empty:
                            cov['silent_pass'] += 1
                            if not is_tk:
                                exc_name = 'Exception'
                                if isinstance(handler.type, ast.Name):
                                    exc_name = handler.type.id
                                elif handler.type is None:
                                    exc_name = 'bare except'
                                findings.append((path, handler.lineno,
                                                 'INFO' if exc_name != 'bare except' else 'HIGH',
                                                 f'silent except ({exc_name}): pass'))
                        elif not has_log and not has_msg:
                            cov['active_no_log'] += 1
                            exc_name = 'Exception'
                            if isinstance(handler.type, ast.Name):
                                exc_name = handler.type.id
                            elif handler.type is None:
                                exc_name = 'bare except'
                            findings.append((path, handler.lineno,
                                             'LOW',
                                             f'except {exc_name}: active handler without logging'))

        return findings, cov, has_logging


# ──────────────────────────────────────────────
# 8. Error message quality
# ──────────────────────────────────────────────

class ErrorMessageQualityAnalyzer:
    def analyze(self, files):
        findings = []

        BAD_PATTERNS = [
            (r'^error$', 'Minimal: just "error"'),
            (r'^exception$', 'Minimal: just "exception"'),
            (r'^failed$', 'Minimal: just "failed"'),
            (r'^unknown$', 'Minimal: just "unknown"'),
            (r'^something went wrong$', 'Vague: no specifics'),
            (r'^error occurred$', 'Vague: no specifics'),
        ]

        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue
            path = short_path(f)

            for node in ast.walk(tree):
                if isinstance(node, ast.Raise):
                    if isinstance(node.exc, ast.Call):
                        for arg in node.exc.args:
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                msg = str(arg.value).lower()
                                for pattern, desc in BAD_PATTERNS:
                                    if re.match(pattern, msg.strip()):
                                        findings.append((path, node.lineno, 'LOW',
                                                         f'Poor error message: "{arg.value[:50]}" - {desc}'))
                                        break

                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        if node.func.attr in ('error', 'warning', 'critical', 'exception'):
                            for arg in node.args:
                                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                                    msg = str(arg.value)
                                    if len(msg.strip()) < 10:
                                        findings.append((path, node.lineno, 'LOW',
                                                         f'Short log message ({len(msg.strip())} chars): "{msg[:40]}"'))
                                        break

        return findings


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def print_sep(title):
    print(f'\n{"=" * 60}')
    print(f'  {title}')
    print('=' * 60)


def main():
    files = get_py_files()
    print(f'RUNTIME HUNT - scanning {len(files)} Python files')
    print('=' * 60)

    results = {}
    all_findings = []

    # 1. Config fields
    print_sep('1. CONFIG FIELD USAGE')
    tracer = ConfigFieldTracer()
    config_fields, field_usage = tracer.analyze(files)

    cfg_files_found = sum(1 for c in tracer.CONFIG_FILES if os.path.exists(os.path.join(PROJECT, c)))
    print(f'  Config files found: {cfg_files_found}')
    for cfg_name in tracer.CONFIG_FILES:
        cfg_path = os.path.join(PROJECT, cfg_name)
        if os.path.exists(cfg_path):
            fields = config_fields.get(cfg_name, set())
            referenced = {k for k in field_usage if k in fields}
            unreferenced = fields - referenced
            if unreferenced:
                print(f'  [{cfg_name}] Unreferenced fields: {", ".join(sorted(unreferenced))}')
                for field in unreferenced:
                    all_findings.append((1, f'{cfg_name}: field "{field}" defined but never read in code'))
            else:
                print(f'  [{cfg_name}] All {len(fields)} fields referenced in code')

    results[1] = len(all_findings)

    # 2. AHK analysis
    print_sep('2. AHK SCRIPT ANALYSIS')
    ahk = AHKAnalyzer()
    meta, ahk_issues = ahk.analyze()
    if meta is None:
        print('  wr_runtime.ahk not found - skipping')
        results[2] = 0
    else:
        print(f'  File: wr_runtime.ahk ({meta["total_lines"]} lines, {meta["num_labels"]} labels, {meta["num_hotkeys"]} hotkeys)')
        print(f'  #Persistent: {meta["has_persistent"]}')
        print(f'  Error handling: {meta["has_error_handling"]}')
        for lineno, severity, msg in ahk_issues:
            print(f'    L{lineno} [{severity}]: {msg}')
            all_findings.append((2, f'AHK L{lineno}: {msg}'))
        results[2] = len(ahk_issues)

    # 3. Process lifecycle
    print_sep('3. PROCESS LIFECYCLE')
    pla = ProcessLifecycleAnalyzer()
    lifecycle = pla.analyze(files)
    if lifecycle:
        print('  Popen / Thread usage:')
        for path, lineno, severity, msg in lifecycle:
            print(f'    {path}:L{lineno} [{severity}]: {msg}')
            all_findings.append((3, f'{path}:L{lineno}: {msg}'))
    else:
        print('  (none found)')
    results[3] = len(lifecycle)

    # 4. Startup flow
    print_sep('4. STARTUP FLOW')
    sfa = StartupFlowAnalyzer()
    chain, imports = sfa.analyze(files)
    print('  Import chain from main.pyw:')
    for i, mod in enumerate(chain[:25]):
        indent = '    ' + '  ' * min(i, 5)
        print(f'  {indent}L{i+1}: {mod}')
        all_findings.append((4, f'Startup: {mod}'))
    if len(chain) > 25:
        print(f'  ... and {len(chain) - 25} more modules')
    results[4] = len(chain)

    # 5. Resource cleanup
    print_sep('5. RESOURCE CLEANUP')
    rca = ResourceCleanupAnalyzer()
    cleanup = rca.analyze(files)
    if cleanup:
        for path, lineno, severity, msg in cleanup:
            print(f'    {path}:L{lineno} [{severity}]: {msg}')
            all_findings.append((5, f'{path}:L{lineno}: {msg}'))
    else:
        print('  (none found)')
    results[5] = len(cleanup)

    # 6. Dead imports
    print_sep('6. DEAD IMPORTS')
    dia = DeadImportAnalyzer()
    dead_imports = dia.analyze(files)
    count6 = 0
    for path in sorted(dead_imports):
        entries = dead_imports[path]
        if entries:
            print(f'\n  {path}:')
            for lineno, name, source in entries[:5]:
                print(f'    L{lineno}: "{name}" from {source} - imported but never used')
                all_findings.append((6, f'{path}:L{lineno}: unused import "{name}"'))
                count6 += 1
            if len(entries) > 5:
                print(f'    ... and {len(entries) - 5} more')
    if count6 == 0:
        print('  (none found)')
    results[6] = count6

    # 7. Logging coverage
    print_sep('7. LOGGING COVERAGE')
    lca = LoggingCoverageAnalyzer()
    log_findings, cov, has_logging = lca.analyze(files)
    print(f'  Project has logging imported: {has_logging}')
    print(f'  Silent pass-only handlers: {cov["silent_pass"]}')
    print(f'  Active handlers without logging: {cov["active_no_log"]}')
    for path, lineno, sev, msg in log_findings:
        print(f'    {path}:L{lineno} [{sev}]: {msg}')
        all_findings.append((7, f'{path}:L{lineno}: {msg}'))
    results[7] = len(log_findings)

    # 8. Error message quality
    print_sep('8. ERROR MESSAGE QUALITY')
    emq = ErrorMessageQualityAnalyzer()
    msg_issues = emq.analyze(files)
    if msg_issues:
        for path, lineno, severity, msg in msg_issues:
            print(f'    {path}:L{lineno} [{severity}]: {msg}')
            all_findings.append((8, f'{path}:L{lineno}: {msg}'))
    else:
        print('  All error messages look informative')
    results[8] = len(msg_issues)

    # Summary
    print('\n' + '=' * 60)
    print('RUNTIME HUNT - SUMMARY')
    print('=' * 60)
    labels = {
        1: 'Config field trace',
        2: 'AHK script analysis',
        3: 'Process lifecycle',
        4: 'Startup flow chain',
        5: 'Resource cleanup',
        6: 'Dead imports',
        7: 'Logging coverage',
        8: 'Error message quality',
    }
    for cat in sorted(results):
        print(f'  Cat {cat} ({labels[cat]:22s}): {results[cat]}')
    print('  ' + '-' * 35)
    cat_sum = sum(results.values())
    print(f'  {"TOTAL":30s}: {cat_sum}')
    print('=' * 60)
    return cat_sum


if __name__ == '__main__':
    sys.exit(main())
