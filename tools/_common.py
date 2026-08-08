"""Shared helpers for the tools/*.hunt scanners (T-122).

Each tool sets ``_common.PROJECT = PROJECT`` after import (module-global
pattern, keeps existing zero-argument call sites working); helpers raise if it
was never set, so a forgotten assignment is loud instead of walking the CWD.
"""

import ast
import os

PROJECT = None


def _require_project():
    if PROJECT is None:
        raise RuntimeError('_common.PROJECT not set — import the helper module '
                           'and assign _common.PROJECT = PROJECT before use')


def get_py_files():
    _require_project()
    result = []
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git')]
        for f in files:
            if f.endswith('.py'):
                result.append(os.path.join(root, f))
    return sorted(result)


def short_path(full_path):
    _require_project()
    p = full_path.replace(PROJECT, '').lstrip('\\\\/')
    return p.replace('\\\\\\\\', '/')


def parse_file(f, verbose=False):
    """Parse a Python file to an AST; None on syntax/encoding errors.

    verbose=True prints the SKIP line (used by ast_hunt so malformed files are
    visible in the scan output instead of silently dropped).
    """
    try:
        with open(f, encoding='utf-8-sig') as fh:
            return ast.parse(fh.read(), f)
    except (SyntaxError, UnicodeDecodeError) as e:
        if verbose:
            print(f'  SKIP {short_path(f)}: {e}')
        return None
