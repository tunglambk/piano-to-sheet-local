"""Gate check for configs/models.lock (Phase 0 plan, Step 5).

Fails (exit 1) if any G0 engine still has a TBD/PENDING field in its code license,
weight license, a weight URL or a weight sha256, or if a sha256 is malformed.

    python scripts/check_lock.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "configs" / "models.lock"
G0_ENGINES = ["transkun_v2", "aria_amt", "beat_this", "pm2s", "m2st"]
BAD = ("TBD", "PENDING")
WARN = ("unknown", "not stated")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def main() -> int:
    data = yaml.safe_load(LOCK.read_text())
    entries = {e["id"]: e for e in data["entries"]}
    failures: list[str] = []
    warnings: list[str] = []
    for engine in G0_ENGINES:
        e = entries.get(engine)
        if e is None:
            failures.append(f"{engine}: missing from {LOCK}")
            continue
        for field in ("code_license", "weight_license"):
            value = str(e.get(field, ""))
            if not value or any(b in value for b in BAD):
                failures.append(f"{engine}: {field} unresolved ({value!r})")
            elif any(b in value for b in WARN):
                warnings.append(f"{engine}: {field} = {value!r} (recorded; covered by D-001)")
        weights = e.get("weights") or []
        if not weights:
            failures.append(f"{engine}: no weights entries")
        for w in weights:
            url = str(w.get("url", ""))
            sha = str(w.get("sha256", ""))
            if not url or "TBD" in url:
                failures.append(f"{engine}: weight URL unresolved ({url!r})")
            if not HEX64.match(sha):
                failures.append(f"{engine}: weight sha256 missing/malformed ({sha!r})")
        if not e.get("license_evidence"):
            failures.append(f"{engine}: license_evidence missing")
        if e.get("status") != "verified":
            failures.append(f"{engine}: status is {e.get('status')!r}, expected 'verified'")

    for w in warnings:
        print("WARN", w)
    if failures:
        print("models.lock G0 check FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print(
        f"models.lock G0 check OK: {len(G0_ENGINES)} engines verified ({len(warnings)} recorded license caveats)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
