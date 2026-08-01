#!/usr/bin/env python3
"""Git-history HUNT — 7 categories from VCS.

Categories:
  1. Commit frequency & timing patterns
  2. File churn rate (most frequently changed files)
  3. Risk hotspots (files with most commits + large diffs)
  4. Code age distribution (oldest vs newest files)
  5. Commit message quality (vague vs informative)
  6. Large commit detection (blob commits)
  7. Refactoring indicators (renames, mass changes)

Usage:  cd <project> && python tools/git_hunt.py
"""

import os
import sys
import subprocess
import re
from collections import defaultdict, Counter
from datetime import datetime, timedelta

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args):
    """Run git command, return stdout lines."""
    try:
        result = subprocess.run(
            ['git'] + list(args),
            capture_output=True, text=True, timeout=30,
            cwd=PROJECT
        )
        return result.stdout.strip().split('\n') if result.stdout.strip() else []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def short_path(full_path):
    p = full_path.replace(PROJECT, '').lstrip('\\/')
    return p.replace('\\\\', '/')


# ──────────────────────────────────────────────
# 1. Commit frequency & timing
# ──────────────────────────────────────────────

class CommitTimingAnalyzer:
    def analyze(self):
        results = []
        log = git('log', '--format=%H|%ai|%an|%s')
        if not log:
            return results, {'total': 0, 'authors': set()}

        commits = []
        authors = set()
        for line in log:
            parts = line.split('|', 3)
            if len(parts) >= 4:
                sha, date, author, msg = parts[0], parts[1], parts[2], parts[3]
                commits.append({'sha': sha, 'date': date, 'author': author, 'msg': msg})
                authors.add(author)

        total = len(commits)
        # Frequency: commits per week
        if total >= 2:
            first = datetime.fromisoformat(commits[-1]['date'])
            last = datetime.fromisoformat(commits[0]['date'])
            span_days = (last - first).days or 1
            freq = total / span_days * 7
        else:
            span_days = 0
            freq = 0

        # Authors
        author_counts = Counter(c['author'] for c in commits)

        results.append(('meta', 'INFO', f'Total commits: {total}'))
        results.append(('meta', 'INFO', f'Authors: {len(authors)} ({", ".join(sorted(authors))})'))
        results.append(('meta', 'INFO', f'Timespan: {span_days} days'))
        results.append(('meta', 'INFO', f'Frequency: {freq:.1f} commits/week'))
        if total > 0:
            # Recent burst: commits in last 7 days
            recent = sum(1 for c in commits
                         if datetime.fromisoformat(c['date']) > datetime.now() - timedelta(days=7))
            results.append(('meta', 'INFO', f'Recent (7d): {recent} commits'))

        return results, {'total': total, 'authors': authors, 'author_counts': author_counts,
                         'span_days': span_days, 'freq': freq}


# ──────────────────────────────────────────────
# 2. File churn rate
# ──────────────────────────────────────────────

class FileChurnAnalyzer:
    def analyze(self):
        results = []
        # Count commits per file using git log --name-only
        log = git('log', '--name-only', '--format=COMMIT:%H', '--diff-filter=AMCR')
        if not log:
            return results

        file_commits = defaultdict(list)
        current_commit = None
        for line in log:
            if line.startswith('COMMIT:'):
                current_commit = line[7:]
            elif line.strip() and current_commit:
                f = line.strip()
                if '.' in f:  # has extension
                    file_commits[f].append(current_commit)

        # Sort by commit count
        sorted_files = sorted(file_commits.items(), key=lambda x: -len(x[1]))

        if sorted_files:
            results.append(('', 'INFO', f'Top 15 most-changed files:'))
            for fname, commits in sorted_files[:15]:
                results.append((f'  {fname}', 'INFO', f'{len(commits)} commits'))
        else:
            results.append(('', 'INFO', 'No file history found'))

        return results


# ──────────────────────────────────────────────
# 3. Risk hotspots (churn × complexity)
# ──────────────────────────────────────────────

class RiskHotspotAnalyzer:
    def analyze(self):
        results = []
        # Get commit count per file AND total diff lines per file
        log = git('log', '--numstat', '--format=', '--diff-filter=AMCR')
        if not log:
            return results

        file_stats = defaultdict(lambda: {'commits': set(), 'added': 0, 'deleted': 0})

        for line in log:
            parts = line.strip().split('\t')
            if len(parts) == 3:
                added, deleted, fname = parts
                if fname == '-':  # binary
                    continue
                if added != '-' and deleted != '-':
                    file_stats[fname]['added'] += int(added)
                    file_stats[fname]['deleted'] += int(deleted)

        # Count commits per file from --name-only (we already have this from cat 2)
        # For now, use numstat only for the risk score
        risks = []
        for fname, stats in file_stats.items():
            total_churn = stats['added'] + stats['deleted']
            # Risk = total_lines_changed (proxy)
            risks.append((total_churn, fname, stats['added'], stats['deleted']))

        risks.sort(reverse=True)
        if risks:
            results.append(('', 'INFO', 'Top 15 risk hotspots (by total churn):'))
            for churn, fname, added, deleted in risks[:15]:
                label = '[HIGH]' if churn > 100 else ('[MED]' if churn > 30 else '[LOW]')
                results.append((f'  {label} {fname}', 'INFO',
                               f'+{added}/-{deleted} = {churn} lines'))

        return results


# ──────────────────────────────────────────────
# 4. Code age (last modified)
# ──────────────────────────────────────────────

class CodeAgeAnalyzer:
    def analyze(self, py_files):
        results = []
        if not py_files:
            return results

        file_ages = []
        for f in py_files:
            sp = short_path(f)
            # git log -1 --format=%ai for each file is slow, use git ls-files
            log = git('log', '-1', '--format=%ai', '--', sp)
            if log:
                date_str = log[0]
                try:
                    last_modified = datetime.fromisoformat(date_str)
                    age_days = (datetime.now() - last_modified).days
                    file_ages.append((age_days, sp, last_modified))
                except ValueError:
                    pass

        if not file_ages:
            return results

        file_ages.sort()

        results.append(('', 'INFO', f'{len(file_ages)} tracked files'))
        # Oldest files (most stable)
        results.append(('', 'INFO', 'Most stable (oldest) files:'))
        for age, sp, dt in file_ages[:5]:
            label = 'STALE' if age > 365 else ('AGING' if age > 180 else 'FRESH')
            results.append((f'  [{label}] {sp}', 'INFO', f'{age}d ago ({dt.date()})'))

        # Newest files (most active)
        results.append(('', 'INFO', 'Hottest (newest) files:'))
        for age, sp, dt in reversed(file_ages[-5:]):
            label = 'HOT'
            results.append((f'  [{label}] {sp}', 'INFO', f'{age}d ago ({dt.date()})'))

        return results


# ──────────────────────────────────────────────
# 5. Commit message quality
# ──────────────────────────────────────────────

class CommitMessageAnalyzer:
    VAGUE_PATTERNS = [
        r'^(update|fix|change|minor|cleanup|wip|temp|tmp|test|foo|blah)$',
        r'^\.$',
        r'^\s*$',
        r'^(update|fix|change)\s+(something|stuff|things|it)$',
        r'^\d+$',
    ]

    def analyze(self):
        results = []
        log = git('log', '--format=%H|%s')
        if not log:
            return results

        total = 0
        vague = 0
        good = 0
        single_word = 0
        has_ticket = 0

        for line in log:
            parts = line.split('|', 1)
            if len(parts) != 2:
                continue
            sha, msg = parts[0], parts[1].strip()
            total += 1

            # Check for vague messages
            is_vague = False
            for pattern in self.VAGUE_PATTERNS:
                if re.match(pattern, msg, re.I):
                    is_vague = True
                    break

            if is_vague:
                vague += 1
                if vague <= 5:
                    results.append(('', 'LOW', f'Vague commit [{sha[:8]}]: "{msg[:50]}"'))
            else:
                good += 1

            # Single word
            if len(msg.split()) == 1 and len(msg) > 2:
                single_word += 1

            # Ticket reference
            if re.match(r'^[A-Z]+-\d+', msg):
                has_ticket += 1

        total_msg = f'Total: {total} commits | Good: {good} ({good*100//total}%) | Vague: {vague} ({vague*100//total}%)'
        if has_ticket:
            total_msg += f' | Ticketed: {has_ticket}'
        if single_word:
            total_msg += f' | Single-word: {single_word}'

        results.insert(0, ('', 'INFO', total_msg))
        return results


# ──────────────────────────────────────────────
# 6. Large commits
# ──────────────────────────────────────────────

class LargeCommitAnalyzer:
    def analyze(self):
        results = []
        log = git('log', '--format=%H|%ai|%an|%s')
        if not log:
            return results

        large_commits = []
        for line in log:
            parts = line.split('|', 3)
            if len(parts) < 4:
                continue
            sha = parts[0]

            # Count files and lines in this commit
            numstat = git('show', '--numstat', '--format=', sha)
            total_added = 0
            total_deleted = 0
            files_changed = 0
            for ns in numstat:
                ns_parts = ns.strip().split('\t')
                if len(ns_parts) == 3 and ns_parts[0] != '-':
                    added, deleted = ns_parts[0], ns_parts[1]
                    total_added += int(added)
                    total_deleted += int(deleted)
                    files_changed += 1

            total_churn = total_added + total_deleted
            if total_churn > 200:
                large_commits.append((total_churn, files_changed, sha, total_added, total_deleted))

        large_commits.sort(reverse=True)
        if large_commits:
            results.append(('', 'INFO', f'{len(large_commits)} large commits (>200 lines):'))
            for churn, files, sha, added, deleted in large_commits[:10]:
                author = git('log', '-1', '--format=%an', sha)
                author_str = author[0] if author else '?'
                results.append((f'  [{sha[:8]}] {author_str}', 'INFO',
                               f'+{added}/-{deleted} = {churn} lines in {files} files'))

        return results


# ──────────────────────────────────────────────
# 8. Refactoring indicators
# ──────────────────────────────────────────────

class RefactoringAnalyzer:
    def analyze(self):
        results = []
        # Detect renames
        renames = git('log', '--diff-filter=R', '--name-only', '--format=%H|%s')
        if renames:
            rename_count = len(renames)
            results.append(('', 'INFO', f'Total renames: {rename_count}'))

        # Detect bulk additions of .py files
        py_additions = git('log', '--diff-filter=A', '--name-only', '--format=COMMIT:%H',
                           '--', '*.py')
        if py_additions:
            current_commit = None
            bulk_adds = 0
            for line in py_additions:
                if line.startswith('COMMIT:'):
                    current_commit = line[7:]
                    # Count .py files added in this commit
                    # (we'll get them in subsequent lines)
                elif line.strip() and current_commit:
                    bulk_adds += 1
            results.append(('', 'INFO', f'Total .py file additions: {bulk_adds}'))

        # Detect .gitignore changes
        gitignore_changes = git('log', '--oneline', '--', '.gitignore')
        if gitignore_changes:
            results.append(('', 'INFO', f'.gitignore changes: {len(gitignore_changes)}'))

        return results


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────

def print_sep(title):
    print(f'\n{"=" * 60}')
    print(f'  {title}')
    print('=' * 60)


def get_py_files():
    result = []
    for root, dirs, files in os.walk(PROJECT):
        dirs[:] = [d for d in dirs if d != '__pycache__' and '.git' not in root]
        for f in files:
            if f.endswith('.py'):
                result.append(os.path.join(root, f))
    return sorted(result)


def main():
    print('GIT HUNT — analyzing commit history')
    print('=' * 60)

    # Check if git repo
    if not git('rev-parse', '--is-inside-work-tree'):
        print('  Not a git repository — aborting')
        return 1

    branch = git('rev-parse', '--abbrev-ref', 'HEAD')
    print(f'  Branch: {branch[0] if branch else "?"}')
    print()

    findings = []

    # 1. Commit timing
    print_sep('1. COMMIT TIMING')
    cta = CommitTimingAnalyzer()
    timing_results, meta = cta.analyze()
    for _, sev, msg in timing_results:
        print(f'  [{sev}] {msg}')
    findings.extend(timing_results)

    # 2. File churn
    print_sep('2. FILE CHURN RATE')
    fca = FileChurnAnalyzer()
    churn_results = fca.analyze()
    for _, sev, msg in churn_results:
        print(f'  [{sev}] {msg}')

    # 3. Risk hotspots
    print_sep('3. RISK HOTSPOTS')
    rha = RiskHotspotAnalyzer()
    risk_results = rha.analyze()
    for _, sev, msg in risk_results:
        print(f'  [{sev}] {msg}')

    # 4. Code age
    print_sep('4. CODE AGE')
    caa = CodeAgeAnalyzer()
    py_files = get_py_files()
    age_results = caa.analyze(py_files)
    for _, sev, msg in age_results:
        print(f'  [{sev}] {msg}')

    # 5. Commit messages
    print_sep('5. COMMIT MESSAGE QUALITY')
    cma = CommitMessageAnalyzer()
    msg_results = cma.analyze()
    for _, sev, msg in msg_results:
        print(f'  [{sev}] {msg}')

    # 6. Large commits
    print_sep('6. LARGE COMMITS')
    lca = LargeCommitAnalyzer()
    large_results = lca.analyze()
    for _, sev, msg in large_results:
        print(f'  [{sev}] {msg}')

    # 7. Refactoring indicators
    print_sep('7. REFACTORING INDICATORS')
    ra = RefactoringAnalyzer()
    refactor_results = ra.analyze()
    for _, sev, msg in refactor_results:
        print(f'  [{sev}] {msg}')

    # Summary
    print(f'\n{"=" * 60}')
    print('  GIT HUNT — SUMMARY')
    print('=' * 60)
    summary_items = [
        f'Total commits: {meta.get("total", 0)}',
        f'Authors: {len(meta.get("authors", set()))}',
        f'Span: {meta.get("span_days", 0)} days',
        f'Frequency: {meta.get("freq", 0):.1f}/week',
    ]
    for item in summary_items:
        print(f'  {item}')
    print('=' * 60)

    return 0


if __name__ == '__main__':
    sys.exit(main())
