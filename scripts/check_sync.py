#!/usr/bin/env python3
"""Measure the Workspace sync against known bar lines (plan step 10, G2).

The browser highlights the measure that contains the playback time, using
`timemap.json`. This script checks the same data: it compares the measure onsets
the pipeline produced with the ground-truth downbeats of the synthetic P2S-Open
items, and reports the error in beats (one beat = the median beat period).

    python scripts/check_sync.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from p2s.core.config import load_config
from p2s.core.pipeline import Pipeline

REPO = Path(__file__).resolve().parents[1]
OPEN = REPO / "data" / "p2s_open" / "v0"


def items(limit: int) -> list[dict]:
    index = json.loads((OPEN / "items.json").read_text())
    chosen = [entry for entry in index if entry["split"] == "dev"][:limit]
    return [
        {
            "id": entry["item_id"],
            "audio": REPO / entry["path"] / "audio.wav",
            "meta": json.loads((REPO / entry["path"] / "meta.json").read_text()),
        }
        for entry in chosen
    ]


def measure_error(measures: list[dict], downbeats: list[float], beat_period: float) -> float | None:
    onsets = [entry["onset_s"] for entry in measures]
    if not onsets or not downbeats:
        return None
    worst = 0.0
    for downbeat in downbeats:
        nearest = min(onsets, key=lambda onset: abs(onset - downbeat))
        worst = max(worst, abs(nearest - downbeat) / beat_period)
    return worst


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--preset", default="accurate")
    parser.add_argument("--data-dir", default=str(REPO / "data"))
    args = parser.parse_args()

    config = load_config()
    rows = []
    for item in items(args.limit):
        meta = item["meta"]
        beats = meta.get("beats", {}).get("beats", [])
        downbeats = meta.get("beats", {}).get("downbeats", [])
        if len(beats) < 2:
            continue
        beat_period = statistics.median(b - a for a, b in zip(beats, beats[1:], strict=False))
        pipeline = Pipeline(config, Path(args.data_dir), job_id=f"sync-{item['id']}")
        result = pipeline.run(item["audio"], args.preset)
        timemap_path = result.artifact("timemap.json")
        timemap = json.loads(Path(timemap_path).read_text())
        error = measure_error(timemap["measures"], downbeats, beat_period)
        rows.append({"item": item["id"], "measures": len(timemap["measures"]), "max_error_beats": error})
        print(
            f"{item['id']}: {len(timemap['measures'])} measures, max error {error:.2f} beats"
            if error is not None
            else f"{item['id']}: no downbeats"
        )

    scored = [row["max_error_beats"] for row in rows if row["max_error_beats"] is not None]
    passed = sum(1 for value in scored if value <= 1.0)
    print(f"\n{passed}/{len(scored)} items within one beat")
    out = REPO / "bench" / "reports" / "phase-2" / "sync.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows, "passed": passed, "n": len(scored)}, indent=1) + "\n")
    return 0 if scored and passed == len(scored) else 1


if __name__ == "__main__":
    raise SystemExit(main())
