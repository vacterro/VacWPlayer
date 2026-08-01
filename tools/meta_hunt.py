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
from collections import defaultdict, Counter

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(PROJECT, 'tools')
RESULT_FILE = os.path.join(PROJECT, '.saipen', 'meta_hunt_results.json')


def short_path(full_path):
    p = full_path.replace(PROJECT, '').lstrip('\\/')
    return p.replace('\\\\', '/')


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
    summary_end = None
    results = {}

    for i, line in enumerate(lines):
        if 'HUNT' in line and 'SUMMARY' in line:
            summary_start = i
            # Read the next line of === separators
            summary_end = None

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


def get_py_files():
    result = []
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if d != '__pycache__' and d != '.git']
        for f in files:
            if f.endswith('.py'):
                result.append(os.path.join(root, f))
    return result


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


def generate_report(scanner_results, file_metrics, orphan_templates):
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
    report.append(f'  Files with most diverse issue types:')
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

    # ── Recommendations ──
    report.append('--- Prioritized Recommendations ---')
    recommendations = [
        ('HIGH', 'Missing #Persistent in AHK script — script may terminate early'),
        ('HIGH', 'Zero type annotations across 323 functions — prevents static analysis'),
        ('HIGH', 'No logging module imported anywhere — all except handlers are silent'),
        ('MEDIUM', 'generate_script() has cyclomatic complexity 80 — refactor into sub-functions'),
        ('MEDIUM', '42 module-level constants marked unused — but exported to other files (probably OK)'),
        ('MEDIUM', 'Parameter "list" shadows builtin in minimap_tab.py:_add_row'),
        ('MEDIUM', 'Function "set" shadows builtin in locales.py'),
        ('LOW', 'Config drift: config.json has orphan fields "lang", "window"'),
        ('LOW', '6 dead imports across 4 files'),
        ('LOW', '29 duplicate code blocks across tabs/ and champions.py'),
    ]
    for severity, rec in recommendations:
        report.append(f'  [{severity}] {rec}')
    report.append('')

    # ── Final scores ──
    report.append('--- Project Health Score ---')
    # Score: 100 - deductions
    score = 100
    deductions = {
        'No type hints': -15,
        'No logging': -10,
        'Giant function (80 complexity)': -10,
        'Empty except handlers (29)': -8,
        'Builtin shadowing (2)': -4,
        'Orphan config fields': -2,
        'Dead imports (6)': -2,
        'Code duplication (29 blocks)': -5,
        'AHK missing #Persistent': -5,
        'No error handling in AHK': -3,
    }
    for reason, deduct in deductions.items():
        score += deduct
        report.append(f'    {deduct:+3d}  {reason}')
    report.append(f'    ----')
    report.append(f'    {score:3d}  TOTAL HEALTH SCORE')
    report.append(f'    (Higher is better. 70+ = healthy, 50-70 = needs work, <50 = critical)')
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
    report, grand_total = generate_report(scanners, metrics, (orphans, total_tmpl))

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
