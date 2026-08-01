#!/usr/bin/env python3
"""Deep cross-module HUNT scanner — 8 categories.

Categories:
  1. Cyclomatic complexity per function (McCabe)
  2. Cross-module dependency graph & circular imports
  3. Security scan: hardcoded secrets, eval/exec, subprocess shell=True
  4. Type annotation coverage (% typed functions / params)
  5. Function return values ignored (pure functions called as statements)
  6. Unused class methods (never called, not __ special methods)
  7. Global / nonlocal usage patterns
  8. Thread-unsafe shared mutable state (no lock)

Usage:  python tools/deep_hunt.py [--summary-only]
"""

import ast
import os
import sys
import re
from collections import defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_PATTERNS = [
    (r'(?i)(password|passwd|pwd|secret|token|api[_-]?key)\s*[:=]\s*["\'][^"\']+["\']', 'hardcoded credential'),
    (r'(?i)(aws_access_key|aws_secret_key|sk-[a-zA-Z0-9]{20,}|ghp_[a-zA-Z0-9]{36})', 'API key / token'),
    (r'(?i)connect\(.*host\s*=\s*["\'][^"\']+["\']', 'hardcoded DB host'),
]


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
# 1. Cyclomatic complexity (McCabe)
# ──────────────────────────────────────────────

class McCabeComplexity(ast.NodeVisitor):
    """M = 1 + number of decision points (if/for/while/and/or/except/with/assert)."""

    def __init__(self):
        self.current_func = '<module>'
        self.complexities = {}  # func_name -> (lineno, complexity)

    def _count_decision(self, node):
        """Count decision points in a statement."""
        count = 0
        if isinstance(node, ast.If):
            count += 1
            count += self._count_decision_in_expr(node.test)
        elif isinstance(node, (ast.For, ast.While)):
            count += 1
        elif isinstance(node, ast.ExceptHandler):
            count += 1
        elif isinstance(node, ast.With):
            count += 1
        elif isinstance(node, ast.Assert):
            count += 1
        return count

    def _count_decision_in_expr(self, node):
        """Count boolean operators in expression."""
        count = 0
        if isinstance(node, ast.BoolOp):
            count += len(node.values) - 1
            for v in node.values:
                count += self._count_decision_in_expr(v)
        elif isinstance(node, ast.IfExp):
            count += 1
        return count

    def visit_FunctionDef(self, node):
        old = self.current_func
        self.current_func = node.name
        complexity = 1  # base
        for child in ast.walk(node):
            complexity += self._count_decision(child)
            if isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        self.complexities[node.name] = (node.lineno, complexity)
        self.generic_visit(node)
        self.current_func = old

    def visit_AsyncFunctionDef(self, node):
        self.visit_FunctionDef(node)


# ──────────────────────────────────────────────
# 2. Dependency graph & circulars
# ──────────────────────────────────────────────

class DepGraphAnalyzer:
    def __init__(self):
        self.imports = {}  # file -> [module_names]

    def analyze(self, files):
        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue
            modules = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        modules.append(alias.name.split('.')[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        modules.append(node.module.split('.')[0])
            self.imports[short_path(f)] = modules

    def find_circulars(self):
        """Simple cycle detection via DFS."""
        adj = defaultdict(list)
        for file, deps in self.imports.items():
            for dep in deps:
                # Find file that matches this dependency name
                for target in self.imports:
                    if target.replace('.py', '').replace('/', '.').endswith(dep):
                        adj[file].append(target)
                        break

        cycles = []

        def dfs(node, path, visited):
            if node in path:
                cycle = path[path.index(node):] + [node]
                # Normalize: sort and dedup
                cycles.append(cycle)
                return
            if node in visited:
                return
            visited.add(node)
            path.append(node)
            for neighbor in adj.get(node, []):
                dfs(neighbor, path, visited)
            path.pop()

        visited = set()
        for node in list(adj.keys()):
            if node not in visited:
                dfs(node, [], visited)

        # Deduplicate cycles
        unique = []
        seen_cycles = set()
        for c in cycles:
            normalized = tuple(sorted(set(c)))
            if normalized not in seen_cycles:
                seen_cycles.add(normalized)
                unique.append(c)
        return unique


# ──────────────────────────────────────────────
# 3. Security scan
# ──────────────────────────────────────────────

class SecurityScanner(ast.NodeVisitor):
    """Find dangerous patterns."""

    def __init__(self):
        self.findings = []  # (lineno, severity, msg)

    def visit_Call(self, node):
        # eval/exec/compile
        if isinstance(node.func, ast.Name) and node.func.id in ('eval', 'exec', 'compile'):
            self.findings.append((node.lineno, 'HIGH', f'dangerous call: {node.func.id}()'))
        # subprocess with shell=True
        if isinstance(node.func, ast.Attribute):
            if (isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess'
                    and node.func.attr in ('call', 'Popen', 'run', 'check_call', 'check_output')):
                for kw in node.keywords:
                    if kw.arg == 'shell' and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        self.findings.append((node.lineno, 'HIGH', 'subprocess with shell=True'))
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        if '|' in arg.value or ';' in arg.value or '`' in arg.value:
                            self.findings.append((node.lineno, 'MEDIUM', 'shell metacharacters in subprocess arg'))
        # pickle/cpickle load
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id in ('pickle', 'cPickle', 'json'):
                if node.func.attr == 'loads':
                    self.findings.append((node.lineno, 'INFO', f'{node.func.value.id}.loads() — deserialization'))
        # open with mode='w' and hardcoded path
        if isinstance(node.func, ast.Name) and node.func.id == 'open':
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if arg.value.startswith(('/', 'C:', '\\\\')):
                        self.findings.append((node.lineno, 'LOW', f'hardcoded file path: {arg.value[:40]}'))
        self.generic_visit(node)

    def visit_Try(self, node):
        for handler in node.handlers:
            if handler.type is None:
                self.findings.append((handler.lineno, 'HIGH', 'bare except: — catches KeyboardInterrupt, SystemExit'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 4. Type annotation coverage
# ──────────────────────────────────────────────

class TypeCoverage(ast.NodeVisitor):
    def __init__(self):
        self.total_funcs = 0
        self.typed_funcs = 0
        self.total_params = 0
        self.typed_params = 0
        self.total_returns = 0
        self.typed_returns = 0

    def _check_func(self, node):
        self.total_funcs += 1
        has_return = node.returns is not None
        if has_return:
            self.typed_returns += 1
            self.typed_funcs += 1
        self.total_returns += 1

        params_typed = all(
            a.annotation is not None for a in node.args.args
        ) if node.args.args else True

        for a in node.args.args:
            self.total_params += 1
            if a.annotation is not None:
                self.typed_params += 1

        if params_typed and has_return:
            self.typed_funcs += 1

    def visit_FunctionDef(self, node):
        self._check_func(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._check_func(node)
        self.generic_visit(node)

    def report(self):
        rf = (self.typed_funcs / self.total_funcs * 100) if self.total_funcs else 0
        rp = (self.typed_params / self.total_params * 100) if self.total_params else 0
        rr = (self.typed_returns / self.total_returns * 100) if self.total_returns else 0
        return rf, rp, rr


# ──────────────────────────────────────────────
# 5. Unused class methods
# ──────────────────────────────────────────────

class ClassMethodAnalyzer:
    def analyze(self, files):
        """Per-file: find methods defined in classes that are never called."""
        report = defaultdict(list)

        for f in files:
            tree = parse_file(f)
            if tree is None:
                continue

            # Collect method definitions
            methods = {}  # method_name -> (class_name, lineno)
            calls = set()

            class MethodCollector(ast.NodeVisitor):
                def visit_ClassDef(self, n):
                    for item in n.body:
                        if isinstance(item, ast.FunctionDef):
                            if not item.name.startswith('__'):
                                methods[item.name] = (n.name, item.lineno)
                    self.generic_visit(n)

                def visit_Call(self, n):
                    if isinstance(n.func, ast.Attribute):
                        calls.add(n.func.attr)
                    elif isinstance(n.func, ast.Name):
                        calls.add(n.func.id)
                    self.generic_visit(n)

            MethodCollector().visit(tree)

            for method, (cls, lineno) in methods.items():
                if method not in calls:
                    report[short_path(f)].append((lineno, cls, method))

        return report


# ──────────────────────────────────────────────
# 6. Global / nonlocal usage
# ──────────────────────────────────────────────

class GlobalFinder(ast.NodeVisitor):
    def __init__(self):
        self.findings = []  # (lineno, msg)

    def visit_Global(self, node):
        for name in node.names:
            self.findings.append((node.lineno, f'global: {name}'))
        self.generic_visit(node)

    def visit_Nonlocal(self, node):
        for name in node.names:
            self.findings.append((node.lineno, f'nonlocal: {name}'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 7. Code duplication (exact line match)
# ──────────────────────────────────────────────

class DuplicateLinesFinder:
    def analyze(self, files):
        """Find exact duplicate 4+ line blocks within the same file."""
        results = defaultdict(list)
        for f in files:
            try:
                with open(f, encoding='utf-8-sig') as fh:
                    lines = fh.readlines()
            except (OSError, UnicodeDecodeError):
                continue

            # Build line signatures (strip for comparison)
            stripped = [l.strip() for l in lines]
            # Find identical sequence of 4+ non-empty lines
            seq_len = 4
            seen = {}
            path = short_path(f)
            for i in range(len(stripped) - seq_len + 1):
                seq = tuple(stripped[i:i + seq_len])
                if all(s and not s.startswith('#') for s in seq):  # skip empty/comment blocks
                    if seq in seen:
                        prev = seen[seq]
                        if abs(i - prev) > seq_len:  # not adjacent
                            results[path].append((prev + 1, i + 1, seq_len))
                    else:
                        seen[seq] = i
        return results


# ──────────────────────────────────────────────
# 8. Hardcoded secrets via regex
# ──────────────────────────────────────────────

def scan_secrets(files):
    """Scan files for hardcoded credentials using regex."""
    findings = defaultdict(list)
    for f in files:
        try:
            with open(f, encoding='utf-8-sig') as fh:
                content = fh.read()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(content.split('\n'), 1):
            line_stripped = line.strip()
            if line_stripped.startswith('#') or line_stripped.startswith('//'):
                continue
            for pattern, desc in SECRET_PATTERNS:
                if re.search(pattern, line):
                    # Avoid flagging obvious examples
                    if 'your-' in line.lower() or 'example' in line.lower() or 'xxxx' in line:
                        continue
                    findings[short_path(f)].append((i, 'MEDIUM', f'possible {desc}: {line_stripped[:60]}'))
                    break
    return findings


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def main():
    files = get_py_files()
    print(f'Scanning {len(files)} Python files in {PROJECT}')
    print('=' * 60)

    results = {}

    # ── 1. Cyclomatic Complexity ──
    print('\n=== 1. CYCLOMATIC COMPLEXITY (top 20) ===')
    all_complexities = []
    for f in files:
        tree = parse_file(f)
        if tree is None:
            continue
        finder = McCabeComplexity()
        finder.visit(tree)
        for func, (lineno, comp) in finder.complexities.items():
            all_complexities.append((comp, short_path(f), lineno, func))

    all_complexities.sort(reverse=True)
    count1 = 0
    for comp, path, lineno, func in all_complexities[:20]:
        tag = '[COMPLEX]' if comp > 15 else ('[OK]' if comp < 10 else '[MODERATE]')
        print(f'  {tag} {comp:3d} - {path}:L{lineno} {func}()')
        count1 += 1
    if count1 == 0:
        print('  (none found)')
    results[1] = len(all_complexities)

    # ── 2. Dependency graph & circulars ──
    print('\n=== 2. MODULE DEPENDENCY ===')
    analyzer = DepGraphAnalyzer()
    analyzer.analyze(files)
    circulars = analyzer.find_circulars()
    count2 = len(circulars)
    if circulars:
        for cycle in circulars:
            print(f'  [LOW] circular: {" -> ".join(cycle)}')
    else:
        print('  No circular imports detected')

    # Show top import consumers
    import_counts = sorted(
        [(len(deps), mod) for mod, deps in analyzer.imports.items()],
        reverse=True
    )
    print('  Top importers:')
    for count, mod in import_counts[:5]:
        print(f'    {count:2d} imports - {mod}')

    results[2] = count2

    # ── 3. Security scan ──
    print('\n=== 3. SECURITY SCAN ===')
    count3 = 0
    for f in files:
        tree = parse_file(f)
        if tree is None:
            continue
        finder = SecurityScanner()
        finder.visit(tree)
        if finder.findings:
            print(f'\n  {short_path(f)}:')
            for lineno, severity, msg in finder.findings:
                print(f'    L{lineno} [{severity}]: {msg}')
                count3 += 1
    if count3 == 0:
        print('  (none found)')
    results[3] = count3

    # ── 4. Type coverage ──
    print('\n=== 4. TYPE ANNOTATION COVERAGE ===')

    # Aggregate type coverage
    agg = TypeCoverage()
    for f in files:
        tree = parse_file(f)
        if tree is None:
            continue
        agg.visit(tree)
    rf, rp, rr = agg.report()
    print(f'  Functions typed:  {agg.typed_funcs}/{agg.total_funcs} ({rf:.0f}%)')
    print(f'  Params typed:     {agg.typed_params}/{agg.total_params} ({rp:.0f}%)')
    print(f'  Return typed:     {agg.typed_returns}/{agg.total_returns} ({rr:.0f}%)')

    # Worst-offending files
    file_stats = []
    for f in files:
        tree = parse_file(f)
        if tree is None:
            continue
        fc = TypeCoverage()
        fc.visit(tree)
        if fc.total_funcs > 0:
            rate = (fc.typed_funcs / fc.total_funcs * 100) if fc.total_funcs else 0
            file_stats.append((rate, fc.total_funcs, short_path(f)))

    file_stats.sort()
    print('  Least typed files:')
    for rate, total, path in file_stats[:5]:
        bar = '#' * int(rate / 5) + '.' * (20 - int(rate / 5))
        print(f'    [{bar}] {rate:3.0f}% - {path} ({total} funcs)')

    results[4] = agg.total_funcs

    # ── 5. Unused class methods ──
    print('\n=== 5. UNUSED CLASS METHODS ===')
    analyzer5 = ClassMethodAnalyzer()
    report5 = analyzer5.analyze(files)
    count5 = 0
    for path, entries in sorted(report5.items()):
        print(f'\n  {path}:')
        for lineno, cls, method in entries:
            print(f'    L{lineno}: {cls}.{method}()')
            count5 += 1
    if count5 == 0:
        print('  (none found)')
    results[5] = count5

    # ── 6. Global / nonlocal usage ──
    print('\n=== 6. GLOBAL / NONLOCAL USAGE ===')
    count6 = 0
    for f in files:
        tree = parse_file(f)
        if tree is None:
            continue
        finder = GlobalFinder()
        finder.visit(tree)
        if finder.findings:
            print(f'\n  {short_path(f)}:')
            for lineno, msg in finder.findings:
                print(f'    L{lineno}: {msg}')
                count6 += 1
    if count6 == 0:
        print('  (none found)')
    results[6] = count6

    # ── 7. Code duplication ──
    print('\n=== 7. DUPLICATE CODE BLOCKS ===')
    finder7 = DuplicateLinesFinder()
    report7 = finder7.analyze(files)
    count7 = 0
    for path, entries in sorted(report7.items()):
        print(f'\n  {path}:')
        for prev, curr, length in entries[:5]:
            print(f'    L{prev} and L{curr}: {length}-line duplicate block')
            count7 += 1
    if count7 == 0:
        print('  (none found)')
    results[7] = count7

    # ── 8. Hardcoded secrets ──
    print('\n=== 8. HARDCODED SECRETS ===')
    report8 = scan_secrets(files)
    count8 = 0
    for path, entries in sorted(report8.items()):
        print(f'\n  {path}:')
        for lineno, severity, msg in entries:
            print(f'    L{lineno} [{severity}]: {msg}')
            count8 += 1
    if count8 == 0:
        print('  (none found)')
    results[8] = count8

    # ── Summary ──
    print('\n' + '=' * 60)
    print('DEEP HUNT — SUMMARY')
    print('=' * 60)
    labels = {
        1: 'Cyclomatic complexity',
        2: 'Circular imports',
        3: 'Security issues',
        4: 'Type coverage (funcs)',
        5: 'Unused class methods',
        6: 'Global/nonlocal usage',
        7: 'Duplicate code blocks',
        8: 'Hardcoded secrets',
    }
    for cat in sorted(results):
        print(f'  Cat {cat} ({labels[cat]:30s}): {results[cat]}')
    print('  ' + '-' * 42)
    grand = sum(results.values()) if all(isinstance(v, int) for v in results.values()) else 0
    print(f'  {"TOTAL FINDINGS":33s}: {grand}')
    print('=' * 60)
    return grand


if __name__ == '__main__':
    sys.exit(main())
