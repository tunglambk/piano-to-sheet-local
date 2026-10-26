#!/usr/bin/env python3
"""Fail when a report references a repository path that does not exist.

Plans and tasks may name files that a future phase will create; reports may not —
a report that points at a missing artefact (or at one a script no longer writes)
is how stale numbers get quoted. This checks `docs/reports/` and `docs/DECISIONS.md`
only, which is where the measured claims live.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TARGETS = [*sorted((REPO / "docs" / "reports").glob("*.md")), REPO / "docs" / "DECISIONS.md"]
PATTERN = re.compile(r"`((?:bench|data|configs|p2s|scripts|apps)/[^`\s]+)`")
# Files that exist only at runtime, never in the repository.
ALLOWED_MISSING = {"data/p2s.db"}


def main() -> int:
    problems: list[str] = []
    for path in TARGETS:
        if not path.exists():
            continue
        for ref in sorted(set(PATTERN.findall(path.read_text()))):
            if path.parent.joinpath(ref).exists() or (REPO / ref).exists():
                continue
            if ref in ALLOWED_MISSING or ref.endswith("/") or any(ch in ref for ch in "*{}<>"):
                continue
            problems.append(f"{path.relative_to(REPO)}: {ref}")
    if problems:
        print("report references a missing path:")
        for line in problems:
            print(f"  - {line}")
        return 1
    print(f"report references OK ({len(TARGETS)} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
