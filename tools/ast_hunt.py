#!/usr/bin/env python3
"""Deep AST-based HUNT scanner — 15 categories.

Categories:
  1.  Unused variables (per scope)
  2.  Uncalled functions (cross-file name resolution)
  3.  Mergeable imports
  4.  Dead code: empty except, unreachable branches, pass-only
  5.  Self-assignment (x = x)
  6.  Dangerous except classification (bare, Exception vs specific)
  7.  Mutable default arguments (def foo(x=[]):)
  8.  Variable shadowing (local shadows builtin/outer)
  9.  None-comparison via == / != (should be is / is not)
  10. Unnecessary else after return/raise/break/continue
  11. Hotspot functions (>50 lines body)
  12. Deep nesting (>4 levels)
  13. Same-arg literal analysis (parameter always gets same literal, file-local)
  14. Bare raise outside except block
  15. Class/function name overlaps builtin

Usage:  python tools/ast_hunt.py [--focus N,...]
Output: grouped by category, severity-annotated
"""

import ast
import os
import sys
from collections import defaultdict

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILTINS = set(dir(__builtins__)) if hasattr(__builtins__, '__dict__') else set()


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
        print(f'  SKIP {short_path(f)}: {e}')
        return None


# ──────────────────────────────────────────────
# 1. Unused variables
# ──────────────────────────────────────────────

class UnusedVarFinder(ast.NodeVisitor):
    def __init__(self):
        self.findings = []

    def _walk_scope(self, node, scope_name, skip_nested=False):
        assigns = {}
        reads = set()

        def _dfs(n):
            if skip_nested and isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                return
            if isinstance(n, ast.Assign):
                for t in n.targets:
                    self._collect_names(t, assigns, n.lineno)
            elif isinstance(n, ast.AnnAssign):
                if n.target:
                    self._collect_names(n.target, assigns, n.lineno)
            elif isinstance(n, ast.With):
                for item in n.items:
                    if item.optional_vars:
                        self._collect_names(item.optional_vars, assigns, n.lineno)
            elif isinstance(n, ast.For):
                if n.target:
                    self._collect_names(n.target, assigns, n.lineno)
            elif isinstance(n, ast.ExceptHandler):
                if n.name:
                    assigns[n.name] = n.lineno
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                reads.add(n.id)
            if isinstance(n, ast.AugAssign):
                self._collect_read_names(n.target, reads)
            for child in ast.iter_child_nodes(n):
                _dfs(child)

        _dfs(node)
        for name, lineno in assigns.items():
            if name not in reads and not name.startswith('_'):
                self.findings.append((lineno, 'INFO', f'"{name}" in {scope_name} — assigned but never read'))

    def _collect_names(self, node, dest, lineno):
        if isinstance(node, ast.Name):
            dest[node.id] = lineno
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                self._collect_names(elt, dest, lineno)
        elif isinstance(node, ast.Starred):
            self._collect_names(node.value, dest, lineno)

    def _collect_read_names(self, node, dest):
        if isinstance(node, ast.Name):
            dest.add(node.id)
        elif isinstance(node, (ast.Tuple, ast.List)):
            for elt in node.elts:
                self._collect_read_names(elt, dest)

    def visit_FunctionDef(self, node):
        self._walk_scope(node, node.name)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._walk_scope(node, node.name)
        self.generic_visit(node)

    def visit_Module(self, node):
        self._walk_scope(node, '<module>', skip_nested=True)
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 2. Uncalled functions (cross-file)
# ──────────────────────────────────────────────

class CallCollector(ast.NodeVisitor):
    def __init__(self):
        self.defs = {}
        self.calls = set()
        self.all_names = set()

    def visit_FunctionDef(self, node):
        if not node.name.startswith('_') or node.name.startswith('__'):
            self.defs[node.name] = (None, node.lineno)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        if not node.name.startswith('_') or node.name.startswith('__'):
            self.defs[node.name] = (None, node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node):
        name = None
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        if name:
            self.calls.add(name)
        self.generic_visit(node)

    def visit_Name(self, node):
        self.all_names.add(node.id)
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 3. Mergeable imports
# ──────────────────────────────────────────────

class ImportMerger(ast.NodeVisitor):
    def __init__(self):
        self.from_imports = defaultdict(list)

    def visit_ImportFrom(self, node):
        if node.level == 0 and node.module:
            for alias in node.names:
                if alias.asname is None:
                    self.from_imports[node.module].append((node.lineno, alias.name))
        self.generic_visit(node)

    def analyze(self):
        self.findings = []
        for module, entries in self.from_imports.items():
            line_groups = defaultdict(list)
            for lineno, name in entries:
                line_groups[lineno].append(name)
            single_lines = [l for l, ns in line_groups.items() if len(ns) == 1]
            if len(single_lines) >= 2:
                all_names = [name for _, name in sorted(entries, key=lambda x: x[0])]
                lines_str = ', '.join(f'L{l}' for l in sorted(single_lines))
                self.findings.append((single_lines[0], 'LOW',
                    f'from {module} import ... merged: lines {lines_str} → from {module} import {", ".join(all_names)}'))


# ──────────────────────────────────────────────
# 4. Dead code patterns
# ──────────────────────────────────────────────

class DeadCodeFinder(ast.NodeVisitor):
    def __init__(self):
        self.findings = []

    def visit_ExceptHandler(self, node):
        if not node.body or all(isinstance(s, ast.Pass) for s in node.body):
            self.findings.append((node.lineno, 'LOW', 'empty except handler (pass only)'))
        self.generic_visit(node)

    def visit_If(self, node):
        if isinstance(node.test, ast.Constant) and not node.test.value:
            self.findings.append((node.lineno, 'MEDIUM', 'unreachable branch: if False/0/None'))
        self.generic_visit(node)

    def visit_FunctionDef(self, node):
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            if not node.name.startswith('_'):
                self.findings.append((node.lineno, 'LOW', f'pass-only function: {node.name}'))
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        if len(node.body) == 1 and isinstance(node.body[0], ast.Pass):
            if not node.name.startswith('_'):
                self.findings.append((node.lineno, 'INFO', f'pass-only class: {node.name}'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 5. Self-assignment (x = x)
# ──────────────────────────────────────────────

class SelfAssignFinder(ast.NodeVisitor):
    def __init__(self):
        self.findings = []

    def visit_Assign(self, node):
        if len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and isinstance(node.value, ast.Name) and t.id == node.value.id:
                self.findings.append((node.lineno, 'MEDIUM', f'self-assignment: {t.id} = {t.id}'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 6. Dangerous except classification
# ──────────────────────────────────────────────

class ExceptClassifier(ast.NodeVisitor):
    """Classify except handlers: bare, too-broad, or ok."""

    SAFE_EXCEPTIONS = {'OSError', 'FileNotFoundError', 'ConnectionError',
                       'TimeoutError', 'tk.TclError', 'TclError',
                       'ValueError', 'TypeError', 'KeyError', 'IndexError',
                       'StopIteration', 'AttributeError', 'ImportError',
                       'json.JSONDecodeError', 'subprocess.CalledProcessError',
                       'Exception'}

    def __init__(self):
        self.findings = []  # (lineno, severity, msg)

    def visit_ExceptHandler(self, node):
        if node.type is None:
            self.findings.append((node.lineno, 'HIGH', 'bare except: — catches KeyboardInterrupt, SystemExit'))
        elif isinstance(node.type, ast.Name) and node.type.id == 'Exception':
            # Check body for logging or meaningful action
            has_action = any(
                not isinstance(s, ast.Pass) and not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))
                for s in (node.body or [])
            )
            if not has_action:
                self.findings.append((node.lineno, 'MEDIUM', 'except Exception: pass — swallows all exceptions silently'))
        elif isinstance(node.type, ast.Tuple):
            # Check if any are too broad
            names = {e.id for e in node.type.elts if isinstance(e, ast.Name)}
            if 'Exception' in names:
                self.findings.append((node.lineno, 'LOW', f'except ({", ".join(names)}): — contains Exception'))
        if not node.body or all(isinstance(s, ast.Pass) for s in node.body):
            has_logging = any('log' in n.id.lower() for n in ast.walk(node) if isinstance(n, ast.Name))
            if not has_logging:
                exc_name = 'bare except' if node.type is None else ast.dump(node.type)[:40]
                self.findings.append((node.lineno, 'INFO', f'silent except ({exc_name}): no logging'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 7. Mutable default arguments
# ──────────────────────────────────────────────

class MutableDefaultsFinder(ast.NodeVisitor):
    """Find def foo(x=[]): or def bar(x={}): or def baz(x=set()):"""

    MUTABLE_TYPES = (ast.List, ast.Dict, ast.Set)

    def __init__(self):
        self.findings = []

    def _check_defaults(self, node):
        # Check actual default values only (annotations are not defaults)
        defaults = node.args.defaults + node.args.kw_defaults
        for d in defaults:
            if d is not None:
                self._check_const(d, node.lineno)

    def _check_const(self, node, lineno):
        if isinstance(node, ast.List):
            self.findings.append((lineno, 'MEDIUM', 'mutable default: []'))
        elif isinstance(node, ast.Dict):
            self.findings.append((lineno, 'MEDIUM', 'mutable default: {}'))
        elif isinstance(node, ast.Set):
            self.findings.append((lineno, 'MEDIUM', 'mutable default: set()'))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ('list', 'dict', 'set'):
                    self.findings.append((lineno, 'MEDIUM', f'mutable default: {node.func.id}()'))

    def visit_FunctionDef(self, node):
        self._check_defaults(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        self._check_defaults(node)
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 8. Variable shadowing
# ──────────────────────────────────────────────

class ShadowingFinder(ast.NodeVisitor):
    """Find local variable names that shadow builtins or outer scope names."""

    def __init__(self):
        self.findings = []

    def visit_FunctionDef(self, node):
        # Collect parameters for this function
        param_names = set()
        for arg in node.args.args + node.args.kwonlyargs + node.args.posonlyargs:
            param_names.add(arg.arg)
        if node.args.vararg:
            param_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            param_names.add(node.args.kwarg.arg)
        # Check parameters against builtins
        for name in param_names:
            if name in BUILTINS:
                self.findings.append((node.lineno, 'LOW', f'param "{name}" shadows builtin in {node.name}'))
        # Check local assignments
        local_names = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                local_names.add(child.id)
        for name in local_names - param_names:
            if name in BUILTINS:
                self.findings.append((node.lineno, 'LOW', f'local "{name}" shadows builtin in {node.name}'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 9. None-comparison via == / !=
# ──────────────────────────────────────────────

class NoneComparisonFinder(ast.NodeVisitor):
    """Find x == None / x != None — should be x is None / x is not None."""

    def __init__(self):
        self.findings = []

    def visit_Compare(self, node):
        for i, op in enumerate(node.ops):
            if isinstance(op, (ast.Eq, ast.NotEq)):
                comparators = [node.left] + node.comparators
                if i + 1 < len(comparators):
                    c = comparators[i + 1]
                    if isinstance(c, ast.Constant) and c.value is None:
                        op_name = '==' if isinstance(op, ast.Eq) else '!='
                        self.findings.append((node.lineno, 'MEDIUM', f'use "is {op_name[-1:]} None" instead of "{op_name} None"'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 10. Unnecessary else after return/raise/break/continue
# ──────────────────────────────────────────────

class UnnecessaryElseFinder(ast.NodeVisitor):
    """Find if/else where the if branch always exits, making else redundant."""

    def __init__(self):
        self.findings = []

    def _check_body(self, body):
        """Check if body unconditionally exits."""
        if not body:
            return False
        last = body[-1]
        if isinstance(last, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
            return True
        if isinstance(last, ast.If):
            return self._check_body(last.body) and self._check_body(last.orelse)
        return False

    def visit_If(self, node):
        if node.orelse and not isinstance(node.orelse[0], ast.If):  # skip elif chains
            if self._check_body(node.body):
                self.findings.append((node.lineno, 'LOW', 'unnecessary else after return/raise/break'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 11. Hotspot functions (>50 lines body)
# ──────────────────────────────────────────────

class HotspotFinder(ast.NodeVisitor):
    def __init__(self):
        self.findings = []

    def _count_lines(self, node):
        if not node.body:
            return 0
        first = node.body[0]
        last = node.body[-1]
        return (last.end_lineno or last.lineno) - (first.lineno - 1)

    def visit_FunctionDef(self, node):
        nlines = self._count_lines(node)
        if nlines > 50:
            self.findings.append((node.lineno, 'INFO', f'long function ({nlines} lines): {node.name}'))
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node):
        nlines = self._count_lines(node)
        if nlines > 50:
            self.findings.append((node.lineno, 'INFO', f'long function ({nlines} lines): {node.name}'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 12. Deep nesting (>4 levels)
# ──────────────────────────────────────────────

class NestingFinder(ast.NodeVisitor):
    def __init__(self):
        self.findings = []
        self.depth = 0

    def _visit_nested(self, node, delta=1):
        self.depth += delta
        if self.depth > 4:
            if isinstance(node, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                self.findings.append((node.lineno, 'LOW', f'nesting depth {self.depth}'))
        self.generic_visit(node)
        self.depth -= delta

    def visit_If(self, node):
        self._visit_nested(node)

    def visit_For(self, node):
        self._visit_nested(node)

    def visit_While(self, node):
        self._visit_nested(node)

    def visit_Try(self, node):
        self._visit_nested(node)

    def visit_With(self, node):
        self._visit_nested(node)

    def visit_FunctionDef(self, node):
        self._visit_nested(node, delta=0)  # don't count function def as nesting

    def visit_AsyncFunctionDef(self, node):
        self._visit_nested(node, delta=0)


# ──────────────────────────────────────────────
# 13. Same-arg literal analysis (file-local inter-procedural)
# ──────────────────────────────────────────────

class SameArgLiteralFinder:
    """For each function, collect all call sites in the same file.
    If a positional argument always gets the same literal, flag it."""

    def __init__(self):
        self.findings = []

    def analyze(self, tree, filename):
        # Phase 1: collect function definitions with their param names
        func_params = {}  # name -> [param_names]
        func_lineno = {}

        class FuncCollector(ast.NodeVisitor):
            def visit_FunctionDef(self, n):
                params = [a.arg for a in n.args.args]
                func_params[n.name] = params
                func_lineno[n.name] = n.lineno
                self.generic_visit(n)

        FuncCollector().visit(tree)

        # Phase 2: collect call sites and their positional args
        calls_by_func = defaultdict(list)  # func_name -> [(lineno, [arg_values])]

        class CallSiteCollector(ast.NodeVisitor):
            def visit_Call(self, n):
                if isinstance(n.func, ast.Name) and n.func.id in func_params:
                    # Only collect positional args (not keyword)
                    pos_args = []
                    for arg in n.args:
                        if isinstance(arg, ast.Constant):
                            pos_args.append((type(arg.value).__name__, repr(arg.value)[:30]))
                        else:
                            pos_args.append(None)  # non-literal
                    if pos_args:
                        calls_by_func[n.func.id].append((n.lineno, pos_args))
                self.generic_visit(n)

        CallSiteCollector().visit(tree)

        # Phase 3: for each function, check if any param always gets the same literal
        for func_name, params in func_params.items():
            calls = calls_by_func.get(func_name, [])
            if len(calls) < 2:
                continue  # need at least 2 call sites to detect pattern
            # For each positional parameter index
            for param_idx, param_name in enumerate(params):
                literals_at_idx = []
                for lineno, pos_args in calls:
                    if param_idx < len(pos_args):
                        val = pos_args[param_idx]
                        if val is not None:
                            literals_at_idx.append((lineno, val))
                if len(literals_at_idx) >= 2:
                    unique_vals = {v for _, v in literals_at_idx}
                    if len(unique_vals) == 1:
                        val = next(iter(unique_vals))
                        self.findings.append((
                            func_lineno.get(func_name, 0),
                            'INFO',
                            f'param "{param_name}" of {func_name}() always gets {val[1]} '
                            f'({len(literals_at_idx)} call sites)'
                        ))


# ──────────────────────────────────────────────
# 14. Bare raise outside except block
# ──────────────────────────────────────────────

class BareRaiseFinder(ast.NodeVisitor):
    """Find 'raise' without argument when not inside an except handler."""

    def __init__(self):
        self.findings = []
        self._in_except = False

    def visit_ExceptHandler(self, node):
        old = self._in_except
        self._in_except = True
        self.generic_visit(node)
        self._in_except = old

    def visit_Raise(self, node):
        if node.exc is None and not self._in_except:
            self.findings.append((node.lineno, 'HIGH', 'bare raise outside except block'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# 15. Name overlaps with builtins
# ──────────────────────────────────────────────

class BuiltinOverlapFinder(ast.NodeVisitor):
    """Find module-level names that shadow Python builtins."""

    def __init__(self):
        self.findings = []

    def visit_FunctionDef(self, node):
        if node.name in BUILTINS and not node.name.startswith('__'):
            self.findings.append((node.lineno, 'LOW', f'function name shadows builtin: {node.name}'))
        self.generic_visit(node)

    def visit_ClassDef(self, node):
        if node.name in BUILTINS:
            self.findings.append((node.lineno, 'LOW', f'class name shadows builtin: {node.name}'))
        self.generic_visit(node)

    def visit_Assign(self, node):
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in BUILTINS:
                self.findings.append((node.lineno, 'LOW', f'module-level var shadows builtin: {t.id}'))
        self.generic_visit(node)


# ──────────────────────────────────────────────
# Analysis runners
# ──────────────────────────────────────────────

def analyze(files, category, func):
    """Generic printer: run func on each file, aggregate results."""
    print(f'\n=== {category} ===')
    total = 0
    for f in files:
        tree = parse_file(f)
        if tree is None:
            continue
        finder = func() if isinstance(func, type) else func()
        if isinstance(finder, ast.NodeVisitor):
            finder.visit(tree)
            if hasattr(finder, 'analyze'):
                finder.analyze()
        else:
            finder.visit(tree)
        findings = getattr(finder, 'findings', [])
        if findings:
            print(f'\n  {short_path(f)}:')
            for lineno, severity, msg in findings:
                print(f'    L{lineno} [{severity}]: {msg}')
                total += 1
    if total == 0:
        print('  (none found)')
    return total


def main():
    files = get_py_files()
    print(f'Scanning {len(files)} Python files in {PROJECT}')
    print('=' * 60)

    results = {}

    results[1] = analyze(files, '1. UNUSED VARIABLES', UnusedVarFinder)

    # 2. Uncalled functions
    print('\n=== 2. UNUSED FUNCTIONS ===')
    project_collector = CallCollector()
    for f in files:
        tree = parse_file(f)
        if tree is None:
            continue
        collector = CallCollector()
        collector.visit(tree)
        for name, (_, lineno) in collector.defs.items():
            if name not in project_collector.defs:
                project_collector.defs[name] = (f, lineno)
        project_collector.calls.update(collector.calls)
        project_collector.all_names.update(collector.all_names)

    entry_points = {'main', 'MainWindow', 'App', 'run', 'start'}
    method_patterns = {'on_', '_on', '__init__', 'tkinter', 'callback',
                       'after', 'bind', 'command', 'event', 'update'}
    count2 = 0
    report2 = defaultdict(list)
    for name, (f, lineno) in sorted(project_collector.defs.items()):
        is_called = name in project_collector.calls or name in project_collector.all_names
        is_entry = name in entry_points
        is_method = any(name.startswith(p) or name.endswith(p) for p in method_patterns)
        is_init = f and f.endswith('__init__.py')
        if not is_called and not is_entry and not is_method and not is_init:
            report2[short_path(f) if f else '<unknown>'].append((lineno, name))
            count2 += 1
    if report2:
        for path, entries in sorted(report2.items()):
            print(f'\n  {path}:')
            for lineno, name in entries:
                print(f'    L{lineno}: {name}')
    else:
        print('  (none found)')
    results[2] = count2

    results[3] = analyze(files, '3. MERGEABLE IMPORTS', ImportMerger)
    results[4] = analyze(files, '4. DEAD CODE PATTERNS', DeadCodeFinder)
    results[5] = analyze(files, '5. SELF-ASSIGNMENT (x = x)', SelfAssignFinder)
    results[6] = analyze(files, '6. EXCEPT CLASSIFICATION', ExceptClassifier)
    results[7] = analyze(files, '7. MUTABLE DEFAULT ARGUMENTS', MutableDefaultsFinder)
    results[8] = analyze(files, '8. VARIABLE SHADOWING', ShadowingFinder)
    results[9] = analyze(files, '9. NONE COMPARISON (== None)', NoneComparisonFinder)
    results[10] = analyze(files, '10. UNNECESSARY ELSE', UnnecessaryElseFinder)
    results[11] = analyze(files, '11. HOTSPOT FUNCTIONS (>50 lines)', HotspotFinder)
    results[12] = analyze(files, '12. DEEP NESTING (>4 levels)', NestingFinder)

    # 13. Same-arg literal (inter-procedural)
    print('\n=== 13. SAME-ARG LITERAL (constant parameter) ===')
    count13 = 0
    for f in files:
        tree = parse_file(f)
        if tree is None:
            continue
        finder = SameArgLiteralFinder()
        finder.analyze(tree, f)
        if finder.findings:
            print(f'\n  {short_path(f)}:')
            for lineno, severity, msg in finder.findings:
                print(f'    L{lineno} [{severity}]: {msg}')
                count13 += 1
    if count13 == 0:
        print('  (none found)')
    results[13] = count13

    results[14] = analyze(files, '14. BARE RAISE OUTSIDE EXCEPT', BareRaiseFinder)
    results[15] = analyze(files, '15. NAME OVERLAPS BUILTIN', BuiltinOverlapFinder)

    # ── Summary ──
    print('\n' + '=' * 60)
    print('DEEP AST HUNT — SUMMARY')
    print('=' * 60)
    labels = {
        1: 'Unused variables', 2: 'Uncalled functions',
        3: 'Mergeable imports', 4: 'Dead code patterns',
        5: 'Self-assignment', 6: 'Except classification',
        7: 'Mutable defaults', 8: 'Variable shadowing',
        9: 'None comparison', 10: 'Unnecessary else',
        11: 'Hotspot functions', 12: 'Deep nesting',
        13: 'Constant params', 14: 'Bare raise',
        15: 'Builtin overlap',
    }
    for cat in sorted(results):
        print(f'  Cat {cat:2d} ({labels[cat]:23s}): {results[cat]}')
    grand = sum(results.values())
    print('  ' + '-' * 35)
    print(f'  {"TOTAL":28s}: {grand}')
    print('=' * 60)
    return grand


if __name__ == '__main__':
    sys.exit(main())
