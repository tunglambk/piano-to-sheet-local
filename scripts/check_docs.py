#!/usr/bin/env python3
"""Documentation check (D-030).

Two jobs:

1. Every relative link between documents must resolve.
2. If `docs/i18n.txt` exists, the documents listed there must be bilingual:
   `X.md` (English, authoritative) plus `X.vi.md` (Vietnamese), both carrying a
   language switcher. The public mirror ships that file; the private working
   repository does not, so during development each document is written once.

Run locally with `python scripts/check_docs.py`; CI runs it as well.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N = ROOT / "docs" / "i18n.txt"
# Operating instructions for coding agents are never published as pairs.
EXEMPT = {Path("AGENTS.md"), Path("CLAUDE.md"), Path("LICENSE"), Path("NOTICE")}
# Archived evidence and generated reports are not living documentation.
EXEMPT_PREFIXES = ("spike/",)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"```.*?```", re.S)
INLINE_CODE = re.compile(r"`[^`\n]*`")


def tracked_markdown() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout.split()
    extra = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "--others", "--exclude-standard", "*.md"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return sorted({Path(p) for p in out + extra})


def counterpart(path: Path) -> Path:
    if path.name.endswith(".vi.md"):
        return path.with_name(path.name[: -len(".vi.md")] + ".md")
    return path.with_name(path.name[: -len(".md")] + ".vi.md")


def bilingual_set() -> set[Path] | None:
    """Documents that must exist in both languages, or None when not enforced."""
    if not I18N.exists():
        return None
    docs: set[Path] = set()
    for line in I18N.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        docs.add(Path(line))
    return docs


def check_links(path: Path) -> list[str]:
    problems: list[str] = []
    text = (ROOT / path).read_text()
    # Links quoted inside code (the switcher format itself, examples in decisions)
    # are documentation, not links to follow.
    text = INLINE_CODE.sub("", FENCE.sub("", text))
    for target in LINK.findall(text):
        if target.startswith(("#", "http://", "https://", "mailto:")) or "://" in target:
            continue
        clean = target.split("#", 1)[0]
        if not clean:
            continue
        if not (ROOT / path.parent / clean).resolve().exists():
            problems.append(f"{path}: broken link -> {target}")
    return problems


def check_pair(path: Path) -> list[str]:
    problems: list[str] = []
    if not (ROOT / path).exists():
        return [f"{path}: missing"]
    other = counterpart(path)
    if not (ROOT / other).exists():
        return [f"{path}: missing counterpart {other}"]
    expected = (
        f"> [English]({other.name}) · **Tiếng Việt**"
        if path.name.endswith(".vi.md")
        else f"> **English** · [Tiếng Việt]({other.name})"
    )
    if expected not in (ROOT / path).read_text():
        problems.append(f"{path}: language switcher line missing ({expected!r})")
    return problems


def documentation() -> list[Path]:
    docs: list[Path] = []
    for path in tracked_markdown():
        if path.parts and path.parts[0] in {"data", "models"}:
            continue
        if any(str(path).startswith(prefix) for prefix in EXEMPT_PREFIXES):
            continue
        if not (ROOT / path).exists():
            # Tracked but deleted in the working tree (mid-edit): the pair check
            # below reports it if it matters.
            continue
        docs.append(path)
    return docs


def main() -> int:
    problems: list[str] = []
    docs = documentation()
    for path in docs:
        problems.extend(check_links(path))

    pairs = bilingual_set()
    if pairs is not None:
        for path in sorted(pairs):
            if path.name.endswith(".vi.md"):
                problems.append(f"docs/i18n.txt lists {path}; list the English file instead")
                continue
            if not (ROOT / path).exists():
                problems.append(f"docs/i18n.txt lists {path}, which does not exist")
                continue
            problems.extend(check_pair(path))
            problems.extend(check_pair(counterpart(path)))

    if problems:
        print("docs check FAILED:")
        for problem in problems:
            print("  -", problem)
        return 1
    suffix = f", {len(pairs)} bilingual pairs" if pairs is not None else ", English only"
    print(f"docs check OK ({len(docs)} markdown files, links resolve{suffix})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
