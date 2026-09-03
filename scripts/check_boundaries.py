#!/usr/bin/env python3
"""CI boundary gate for the Sovereign Ledger (hard rule 1 + module-name rule).

Scans the pure domain trees — ``ledger/`` and ``reports/`` — for:

1. Forbidden I/O tokens: any occurrence of the word-bounded regex

       \\b(?:fastapi|psycopg|asyncpg|requests|httpx)\\b

   i.e. web framework / database driver / HTTP client names. Any hit,
   even inside a comment, is a violation — keep the pure trees clean.
   Word boundaries are used so longer identifiers never false-positive.

2. Forbidden catch-all module names: any module (``*.py`` stem) or
   package directory named ``utils``, ``helpers``, ``common``, or
   ``shared`` — junk drawers are banned by the boundary rules.

``reports/`` may not exist yet (greenfield); a missing pure tree passes.
Exit codes: ``0`` = clean, ``1`` = at least one violation (every hit is
printed). Run it as::

    uv run python scripts/check_boundaries.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PURE_TREES: tuple[str, ...] = ("ledger", "reports")
FORBIDDEN_IMPORT = re.compile(r"\b(?:fastapi|psycopg|asyncpg|requests|httpx)\b")
FORBIDDEN_MODULE_NAMES = frozenset({"utils", "helpers", "common", "shared"})


def scan() -> tuple[list[str], list[str], list[str]]:
    """Return (violations, scanned_trees, absent_trees)."""
    violations: list[str] = []
    scanned: list[str] = []
    absent: list[str] = []
    for tree in PURE_TREES:
        root = REPO_ROOT / tree
        if not root.is_dir():
            absent.append(tree)
            continue
        scanned.append(tree)
        for path in sorted(root.rglob("*")):
            if "__pycache__" in path.parts:
                continue
            rel = path.relative_to(REPO_ROOT)
            if path.is_dir():
                if path.name in FORBIDDEN_MODULE_NAMES:
                    violations.append(f"{rel}: forbidden package name {path.name!r}")
            elif path.suffix == ".py":
                if path.stem in FORBIDDEN_MODULE_NAMES:
                    violations.append(f"{rel}: forbidden module name {path.stem!r}")
                text = path.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if FORBIDDEN_IMPORT.search(line):
                        violations.append(f"{rel}:{lineno}: forbidden I/O token: {line.strip()}")
    return violations, scanned, absent


def main() -> int:
    violations, scanned, absent = scan()
    if violations:
        print(
            f"boundary gate: {len(violations)} violation(s) under {PURE_TREES}:",
            file=sys.stderr,
        )
        for violation in violations:
            print(f"  {violation}", file=sys.stderr)
        return 1
    print(
        f"boundary gate: clean — scanned {scanned or 'nothing'}, "
        f"absent (pass): {absent or 'none'}; "
        "no forbidden I/O tokens, no junk-drawer module names"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())