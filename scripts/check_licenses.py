"""License register check (D-013, D-027).

Fails when a register entry lacks a license, when a copyleft entry has no note,
when a shipped (runtime) entry is unknown and unexplained, or when the repository
licence files disagree with each other.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REGISTER = ROOT / "configs" / "licenses.yaml"
COPYLEFT = ("GPL", "LGPL", "AGPL", "MPL")
EXPECTED_SPDX = "PolyForm-Noncommercial-1.0.0"


def check_repository_license() -> list[str]:
    """Keep LICENSE, NOTICE and pyproject.toml in sync (D-027)."""
    failures: list[str] = []
    license_path = ROOT / "LICENSE"
    notice_path = ROOT / "NOTICE"
    if not license_path.exists():
        return ["LICENSE is missing"]
    text = license_path.read_text()
    if f"SPDX-License-Identifier: {EXPECTED_SPDX}" not in text:
        failures.append(f"LICENSE does not declare {EXPECTED_SPDX}")
    if "PolyForm Noncommercial License 1.0.0" not in text:
        failures.append("LICENSE does not contain the PolyForm Noncommercial text")
    if "polyformproject.org/licenses/noncommercial/1.0.0" not in text:
        failures.append("LICENSE does not point at the canonical text")
    if not notice_path.exists():
        failures.append("NOTICE is missing")
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    declared = project.get("license")
    if declared != EXPECTED_SPDX:
        failures.append(f"pyproject license is {declared!r}, expected {EXPECTED_SPDX!r}")
    if "LICENSE" not in project.get("license-files", []):
        failures.append("pyproject license-files does not include LICENSE")
    return failures


def main() -> int:
    data = yaml.safe_load(REGISTER.read_text())
    failures: list[str] = []
    for entry in data.get("entries", []):
        name = entry.get("name", "?")
        license_text = str(entry.get("license", "")).strip()
        if not license_text:
            failures.append(f"{name}: no license recorded")
            continue
        if not entry.get("evidence"):
            failures.append(f"{name}: no license evidence")
        if any(word in license_text.upper() for word in COPYLEFT) and not entry.get("notes"):
            failures.append(f"{name}: copyleft license ({license_text}) without a note")
        if "unknown" in license_text.lower() and entry.get("scope") == "runtime" and not entry.get("notes"):
            failures.append(f"{name}: runtime entry with unknown license and no note")
    failures.extend(check_repository_license())
    if failures:
        print("license register check FAILED:")
        for failure in failures:
            print("  -", failure)
        return 1
    print(f"license register OK ({len(data.get('entries', []))} entries; project {EXPECTED_SPDX})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
