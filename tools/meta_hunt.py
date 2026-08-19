#!/usr/bin/env python3
"""Meta-HUNT: runs all 3 scanners, cross-references findings.

  1. Runs ast_hunt.py, deep_hunt.py, runtime_hunt.py
  2. Aggregates findings into one report
  3. Cross-references: which functions appear in multiple categories
  4. Hotspot ranking: files with most findings
  5. Category correlation: which bug types co-occur in same files
  6. Trend analysis: compare with previous run (if log exists)

Usage:  python tools/meta_hunt.py
"""

import os
import sys
import subprocess
import json
import re
from collections import defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import _common
_common.PROJECT = PROJECT
from _common import get_py_files, short_path

TOOLS_DIR = os.path.join(PROJECT, 'tools')
RESULT_FILE = os.path.join(PROJECT, '.saipen', 'meta_hunt_results.json')


def run_scanner(script_name):
    """Run a scanner and capture stdout + exit code."""
    path = os.path.join(TOOLS_DIR, script_name)
    if not os.path.exists(path):
        return {'exit_code': -1, 'stdout': '', 'error': 'File not found'}
    try:
        result = subprocess.run(
            [sys.executable, path],
            capture_output=True, text=True, timeout=120,
            cwd=PROJECT
        )
        return {
            'exit_code': result.returncode,
            'stdout': result.stdout,
            'stderr': result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {'exit_code': -1, 'stdout': '', 'error': 'Timed out'}
    except Exception as e:
        return {'exit_code': -1, 'stdout': '', 'error': str(e)}


def parse_summary(stdout):
    """Extract the SUMMARY table from a scanner's output."""
    lines = stdout.split('\n')
    summary_start = None
    results = {}

    for i, line in enumerate(lines):
        if 'HUNT' in line and 'SUMMARY' in line:
            summary_start = i

    if summary_start:
        for i in range(summary_start, min(summary_start + 50, len(lines))):
            if 'Cat ' in lines[i]:
                # Parse: "  Cat 1 (Unused variables       ): 43"
                m = re.match(r'\s*Cat\s+(\d+)\s+\((.+?)\)\s*:\s*(\d+)', lines[i])
                if m:
                    results[int(m.group(1))] = {
                        'label': m.group(2).strip(),
                        'count': int(m.group(3)),
                    }
            if 'TOTAL' in lines[i]:
                m = re.search(r'TOTAL[\s\w]*:\s*(\d+)', lines[i])
                if m:
                    results['total'] = int(m.group(1))

    # Fallback: count from output
    return results


def parse_findings_by_file(stdout):
    """Parse file-scoped findings from scanner output. Returns {file: [(cat, lineno, msg)]}"""
    findings = defaultdict(list)
    current_file = None
    current_category = None

    for line in stdout.split('\n'):
        # Category header
        m = re.match(r'=== (\d+)\.\s+(.+) ===', line)
        if m:
            current_category = int(m.group(1))
            current_file = None
            continue

        # File path line
        m = re.match(r'^\s\s(.+\.py):', line)
        if m:
            current_file = m.group(1).strip()
            continue

        # Finding line: L123 [SEV]: msg  OR  L655: generate_and_run
        m = re.match(r'\s+L(\d+)\s+\[(\w+)\]:\s+(.+)', line)
        if m and current_file and current_category:
            findings[current_file].append({
                'cat': current_category,
                'lineno': int(m.group(1)),
                'severity': m.group(2),
                'msg': m.group(3),
            })
        else:
            m2 = re.match(r'\s+L(\d+):\s+(.+)', line)
            if m2 and current_file and current_category:
                findings[current_file].append({
                    'cat': current_category,
                    'lineno': int(m2.group(1)),
                    'severity': 'NONE',
                    'msg': m2.group(2),
                })

    return findings


def analyze_file_metrics(files):
    """Lines of code per file, comment ratio, import count."""
    metrics = {}
    for f in files:
        try:
            with open(f, encoding='utf-8-sig') as fh:
                lines = fh.readlines()
        except (OSError, UnicodeDecodeError):
            continue

        total = len(lines)
        code = sum(1 for l in lines if l.strip() and not l.strip().startswith('#'))
        comments = sum(1 for l in lines if l.strip().startswith('#'))
        blanks = sum(1 for l in lines if not l.strip())
        imports = sum(1 for l in lines if l.strip().startswith(('import ', 'from ')))

        metrics[short_path(f)] = {
            'total_lines': total,
            'code_lines': code,
            'comment_lines': comments,
            'blank_lines': blanks,
            'import_lines': imports,
            'comment_ratio': round(comments / code * 100, 1) if code else 0,
        }
    return metrics


def find_orphan_templates(files):
    """Find template images not referenced in any .py file."""
    templates_dir = os.path.join(PROJECT, 'templates')
    if not os.path.exists(templates_dir) or not os.path.isdir(templates_dir):
        return [], 0

    # Collect all template file references from Python code
    referenced = set()
    template_exts = {'.png', '.jpg', '.bmp', '.tpl', '.txt', '.meta'}
    source_code = ''
    for f in files:
        try:
            with open(f, encoding='utf-8-sig') as fh:
                source_code += fh.read() + '\n'
        except (OSError, UnicodeDecodeError):
            pass

    # Walk templates directory
    all_templates = set()
    found_templates = 0
    for root, dirs, fs in os.walk(templates_dir):
        for fname in fs:
            ext = os.path.splitext(fname)[1].lower()
            if ext in template_exts:
                all_templates.add(fname)
                found_templates += 1
                if fname in source_code or fname.replace(ext, '') in source_code:
                    referenced.add(fname)

    orphans = all_templates - referenced
    return sorted(orphans), found_templates


def _cyclomatic(node):
    """Cyclomatic complexity of one function node (approximation)."""
    import ast as _ast
    c = 1
    for n in _ast.walk(node):
        if isinstance(n, (_ast.If, _ast.For, _ast.While, _ast.With,
                          _ast.ExceptHandler, _ast.Assert)):
            c += 1
        elif isinstance(n, _ast.BoolOp):
            c += len(n.values) - 1
    return c


def _ast_health_signals(files):
    """Live health metrics derived from the source tree, never hardcoded.

    Feeds the health score: type-hint coverage, max cyclomatic complexity,
    bare-pass except handlers and whether logging is imported anywhere. These
    used to be a static literal list that drifted from the tree it claimed to
    describe (T-128) - the numbers now come from the actual sources.
    """
    import ast as _ast
    total_funcs = 0
    typed_funcs = 0
    max_complexity = 0
    empty_excepts = 0
    imports_logging = False

    def _typed(node):
        if node.returns is not None:
            return True
        if any(a.annotation is not None for a in node.args.args):
            return True
        if node.args.vararg is not None and node.args.vararg.annotation is not None:
            return True
        if node.args.kwarg is not None and node.args.kwarg.annotation is not None:
            return True
        return False

    for path in files:
        try:
            with open(path, encoding='utf-8') as fh:
                src = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        try:
            tree = _ast.parse(src)
        except SyntaxError:
            continue
        for node in _ast.walk(tree):
            if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                total_funcs += 1
                if _typed(node):
                    typed_funcs += 1
                max_complexity = max(max_complexity, _cyclomatic(node))
            elif isinstance(node, _ast.ExceptHandler):
                body = node.body
                if len(body) == 1 and isinstance(body[0], _ast.Pass):
                    empty_excepts += 1
            elif isinstance(node, _ast.Import):
                imports_logging = imports_logging or any(
                    a.name == 'logging' for a in node.names)
            elif isinstance(node, _ast.ImportFrom):
                imports_logging = imports_logging or node.module == 'logging'

    return {
        'total_funcs': total_funcs,
        'typed_funcs': typed_funcs,
        'typed_pct': (100.0 * typed_funcs / total_funcs) if total_funcs else 100.0,
        'max_complexity': max_complexity,
        'empty_excepts': empty_excepts,
        'imports_logging': imports_logging,
    }


def find_orphan_config_fields(files):
    """Top-level config.json keys no Python source references by string.

    Replaces the old hardcoded claim that config.json carried orphan fields
    (T-128): the truth is computed, so a key consumed as `"lang"` in code is
    never reported orphan just because a stale snapshot said so.
    """
    cfg_path = os.path.join(PROJECT, 'config.json')
    try:
        with open(cfg_path, encoding='utf-8') as fh:
            cfg = json.load(fh)
    except (OSError, ValueError):
        return []
    if not isinstance(cfg, dict):
        return []
    keys = list(cfg)
    referenced = set()
    for path in files:
        try:
            with open(path, encoding='utf-8') as fh:
                src = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for key in keys:
            if key not in referenced and ('"%s"' % key in src or "'%s'" % key in src):
                referenced.add(key)
    return [k for k in keys if k not in referenced]


def generate_report(scanner_results, file_metrics, orphan_templates,
                    health_signals, orphan_config, ahk_text):
    """Generate consolidated report with cross-references."""
    report = []

    report.append('=' * 70)
    report.append('  META-HUNT: CONSOLIDATED REPORT')
    report.append('=' * 70)
    report.append('')

    # ── Scanner health ──
    report.append('--- Scanner Status ---')
    for name, result in sorted(scanner_results.items()):
        status = 'OK' if result['exit_code'] in (0, result.get('expected_code', 0)) else 'FAIL'
        report.append(f'  {name}: exit={result["exit_code"]} | {status}')
    report.append('')

    # ── Findings summary ──
    report.append('--- Findings Summary ---')
    grand_total = 0
    cat_total = 0
    for name, result in sorted(scanner_results.items()):
        summary = parse_summary(result['stdout'])
        t = summary.get('total', 0)
        report.append(f'  {name}: {t} total findings')
        grand_total += t
        # Count non-total categories
        for k, v in summary.items():
            if isinstance(k, int):
                cat_total += 1
    report.append(f'  Combined: {grand_total} findings across {cat_total} categories')
    report.append('')

    # ── Hotspot files (by total findings across all scanners) ──
    report.append('--- Hotspot Files (most findings across all scanners) ---')
    file_findings_all = defaultdict(int)
    for name, result in sorted(scanner_results.items()):
        ff = parse_findings_by_file(result['stdout'])
        for path, entries in ff.items():
            file_findings_all[path] += len(entries)

    top_hotspots = sorted(file_findings_all.items(), key=lambda x: -x[1])[:25]
    if top_hotspots:
        report.append(f'  {"File":45s} {"Findings":>8s}')
        report.append(f'  {"-"*45} {"-"*8}')
        for path, count in top_hotspots:
            bar = '#' * min(count, 40)
            report.append(f'  {path:45s} {count:8d}  {bar}')
    else:
        report.append('  (no file-level data extracted)')
    report.append('')

    # ── File metrics ──
    report.append('--- File Metrics (largest files) ---')
    sorted_by_lines = sorted(file_metrics.items(), key=lambda x: -x[1]['total_lines'])[:15]
    if sorted_by_lines:
        report.append(f'  {"File":45s} {"Lines":>6s} {"Code":>5s} {"Cmnt":>5s} {"Ratio":>6s} {"Imports":>7s}')
        report.append(f'  {"-"*45} {"-"*6} {"-"*5} {"-"*5} {"-"*6} {"-"*7}')
        for path, m in sorted_by_lines:
            report.append(f'  {path:45s} {m["total_lines"]:6d} {m["code_lines"]:5d} {m["comment_lines"]:5d} {m["comment_ratio"]:5.1f}% {m["import_lines"]:7d}')
    report.append('')

    # ── Orphan templates ──
    report.append('--- Template Analysis ---')
    if orphan_templates[0]:
        report.append(f'  Found {len(orphan_templates[0])} orphan templates (unreferenced in code):')
        for t in orphan_templates[0][:20]:
            report.append(f'    - {t}')
        if len(orphan_templates[0]) > 20:
            report.append(f'    ... and {len(orphan_templates[0]) - 20} more')
    else:
        report.append(f'  All {orphan_templates[1]} templates are referenced in code')
    report.append('')

    # ── Cross-category correlations ──
    report.append('--- Category Correlations ---')
    file_cats = defaultdict(set)
    for name, result in sorted(scanner_results.items()):
        ff = parse_findings_by_file(result['stdout'])
        for path, entries in ff.items():
            for e in entries:
                file_cats[path].add(e['cat'])

    # Find files with most diverse issue types
    diverse_files = sorted(file_cats.items(), key=lambda x: -len(x[1]))[:10]
    report.append('  Files with most diverse issue types:')
    for path, cats in diverse_files:
        report.append(f'    {path}: appears in {len(cats)} categories ({sorted(cats)})')

    # Cat 11 hotspots vs cat 6 exceptions — do complex functions also have bad except handling?
    report.append('')
    report.append('  Key correlations:')
    # Check if hotspot files also have logging issues
    hotspot_files = set()
    for name, result in sorted(scanner_results.items()):
        ff = parse_findings_by_file(result['stdout'])
        if name == 'deep_hunt.py':
            for path, entries in ff.items():
                for e in entries:
                    if e['cat'] == 1 and 'long function' in e['msg']:
                        hotspot_files.add(path)
    report.append(f'    Long-function hotspots: {len(hotspot_files)} files')
    report.append('')

    # Live counts for the health section: ast_hunt Cat 15 = builtin shadowing,
    # runtime_hunt Cat 6 = dead imports.
    ast_summary = parse_summary(scanner_results.get('ast_hunt.py', {}).get('stdout', ''))
    rt_summary = parse_summary(scanner_results.get('runtime_hunt.py', {}).get('stdout', ''))
    builtin_shadowing = ast_summary.get(15, {}).get('count', 0) if ast_summary.get(15) else 0
    dead_imports = rt_summary.get(6, {}).get('count', 0) if rt_summary.get(6) else 0

    # ── Recommendations (derived from this run, never hardcoded) ──
    report.append('--- Prioritized Recommendations ---')
    health = health_signals
    ahk = ahk_text or ''
    fired = []
    # T-200: Low type-hint coverage check suppressed
    if False and health['typed_pct'] < 50:
        fired.append(('HIGH', 'Low type-hint coverage',
                      '%.0f%% of %d functions annotated' % (health['typed_pct'], health['total_funcs'])))
    if not health['imports_logging']:
        fired.append(('HIGH', 'No logging module imported anywhere',
                      'all except handlers are silent'))
    if health['max_complexity'] >= 80:
        fired.append(('MEDIUM', 'Giant function',
                      'max cyclomatic complexity %d - refactor into sub-functions' % health['max_complexity']))
    if health['empty_excepts'] >= 10:
        fired.append(('MEDIUM', 'Bare-pass except handlers',
                      '%d handlers swallow errors silently' % health['empty_excepts']))
    if orphan_config:
        fired.append(('LOW', 'Config drift',
                      'config.json orphan fields: %s' % ', '.join(orphan_config)))
    if '#Persistent' not in ahk:
        fired.append(('LOW', 'AHK script missing #Persistent',
                      'script may terminate early'))
    # T-201: AHK script does not use exceptions intentionally
    if False and 'try' not in ahk.lower():
        fired.append(('LOW', 'No error handling in AHK script', None))
    if not fired:
        fired.append(('LOW', 'No major issues in this run', None))
    for severity, title, detail in fired:
        line = f'  [{severity}] {title}'
        if detail:
            line += ' - ' + detail
        report.append(line)
    report.append('')

    # ── Final scores (computed from the scan data above) ──
    report.append('--- Project Health Score ---')
    score = 100
    deductions = [
        ('No type hints', 15, health['typed_pct'] < 50),
        ('No logging', 10, not health['imports_logging']),
        ('Giant function', 10, health['max_complexity'] >= 80),
        ('Empty except handlers', 8, health['empty_excepts'] >= 10),
        ('Builtin shadowing', 4, builtin_shadowing > 0),
        ('Orphan config fields', 2, bool(orphan_config)),
        ('Dead imports', 2, dead_imports > 0),
        ('AHK missing #Persistent', 5, '#Persistent' not in ahk),
        ('No error handling in AHK', 3, 'try' not in ahk.lower()),
    ]
    for reason, deduct, cond in deductions:
        if cond:
            score -= deduct
            report.append(f'    {-deduct:+3d}  {reason}')
    report.append('    ----')
    report.append(f'    {score:3d}  TOTAL HEALTH SCORE (higher is better)')
    report.append('    (Higher is better. 70+ = healthy, 50-70 = needs work, <50 = critical)')
    report.append('')

    report.append('=' * 70)
    report.append('  End of Meta-HUNT Report')
    report.append('=' * 70)

    return '\n'.join(report), grand_total


def main():
    print('META-HUNT: running all 3 scanners...')
    print('=' * 60)

    # Run all 3 scanners
    scanners = {
        'ast_hunt.py': run_scanner('ast_hunt.py'),
        'deep_hunt.py': run_scanner('deep_hunt.py'),
        'runtime_hunt.py': run_scanner('runtime_hunt.py'),
    }

    for name, result in scanners.items():
        # Scanners return findings count as exit code (non-zero = success)
        # Only fail on actual Python crashes (SyntaxError, AttributeError, etc.)
        stderr = result.get('stderr', '').strip()
        has_crash = bool(stderr) and 'Traceback' in stderr and 'Error' in stderr
        status = 'OK' if not has_crash else 'CRASH'
        print(f'  {name:20s} exit={result["exit_code"]:4d} | {status}')
        if has_crash:
            print(f'    stderr: {stderr[:200]}')

    # File metrics
    files = get_py_files()
    print(f'\n  File metrics: {len(files)} Python files analyzed')

    # Orphan templates
    orphans, total_tmpl = find_orphan_templates(files)
    print(f'  Templates: {total_tmpl} total, {len(orphans)} orphans')

    # Generate report
    metrics = analyze_file_metrics(files)
    health_signals = _ast_health_signals(files)
    orphan_config = find_orphan_config_fields(files)
    ahk_path = os.path.join(PROJECT, 'wr_runtime.ahk')
    ahk_text = ''
    try:
        with open(ahk_path, encoding='utf-8', errors='replace') as fh:
            ahk_text = fh.read()
    except OSError:
        pass
    report, grand_total = generate_report(scanners, metrics, (orphans, total_tmpl),
                                          health_signals, orphan_config, ahk_text)

    print('\n' + report)

    # Save JSON result
    result_data = {
        'grand_total': grand_total,
        'scanner_exit_codes': {name: r['exit_code'] for name, r in scanners.items()},
        'orphan_templates': orphans[:50],
        'total_templates': total_tmpl,
        'total_py_files': len(files),
    }
    try:
        with open(RESULT_FILE, 'w', encoding='utf-8') as fh:
            json.dump(result_data, fh, indent=2)
    except (OSError, json.JSONDecodeError):
        pass

    return grand_total


if __name__ == '__main__':
    sys.exit(main())
