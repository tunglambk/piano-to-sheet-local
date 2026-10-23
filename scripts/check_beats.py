#!/usr/bin/env python3
"""Measure the downbeat tracker against the annotated P2S-Open beats (P4 plan §0a).

Reports, per dev item: beat F-measure (+-70 ms), downbeat F-measure, and the
beats-per-bar the tracker implies versus the annotated one. This separates a
tracking problem (beats wrong) from a metre problem (beats right, bars wrong).

    python scripts/check_beats.py --limit 5
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path

import soundfile

from p2s.core.cache import sha256_file
from p2s.core.config import load_config
from p2s.core.schemas import AudioRef, MeterHints
from p2s.engines.registry import create_engine

REPO = Path(__file__).resolve().parents[1]
OPEN = REPO / "data" / "p2s_open" / "v0"
TOLERANCE_S = 0.07


def f_measure(predicted: list[float], truth: list[float], tolerance: float = TOLERANCE_S) -> float:
    if not predicted or not truth:
        return 0.0
    used = [False] * len(truth)
    hits = 0
    for value in predicted:
        best, best_cost = -1, tolerance
        for index, target in enumerate(truth):
            if used[index]:
                continue
            cost = abs(value - target)
            if cost <= best_cost:
                best, best_cost = index, cost
        if best >= 0:
            used[best] = True
            hits += 1
    precision = hits / len(predicted)
    recall = hits / len(truth)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def bars_per_bar(beats: list[float], downbeats: list[float]) -> int:
    counts: Counter[int] = Counter()
    for previous, current in zip(downbeats, downbeats[1:], strict=False):
        n = sum(1 for beat in beats if previous - 1e-6 <= beat < current - 1e-6)
        if 2 <= n <= 12:
            counts[n] += 1
    return counts.most_common(1)[0][0] if counts else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--engine", default="beat_this")
    args = parser.parse_args()

    config = load_config()
    engine = create_engine(config, "beats", args.engine)
    index = json.loads((OPEN / "items.json").read_text())
    rows = []
    for entry in [item for item in index if item["split"] == "dev"][: args.limit]:
        folder = REPO / entry["path"]
        audio = folder / "audio.wav"
        meta = json.loads((folder / "meta.json").read_text())
        truth_beats = meta["beats"]["beats"]
        truth_downbeats = meta["beats"]["downbeats"]
        info = soundfile.info(audio)
        ref = AudioRef(
            path=str(audio),
            sha256=sha256_file(audio),
            sample_rate=int(info.samplerate),
            channels=int(info.channels),
            duration_s=float(info.duration),
        )
        grid = engine.track(ref, MeterHints())
        row = {
            "item": entry["item_id"],
            "beat_f": round(f_measure(grid.beats, truth_beats), 3),
            "downbeat_f": round(f_measure(grid.downbeats, truth_downbeats), 3),
            "bars_per_bar_pred": bars_per_bar(grid.beats, grid.downbeats),
            "bars_per_bar_truth": bars_per_bar(truth_beats, truth_downbeats),
            "n_beats": len(grid.beats),
            "n_downbeats": len(grid.downbeats),
            "truth_beats": len(truth_beats),
            "truth_downbeats": len(truth_downbeats),
        }
        rows.append(row)
        print(
            f"{row['item']:22} beatF {row['beat_f']:.2f}  downbeatF {row['downbeat_f']:.2f}  "
            f"bpb {row['bars_per_bar_pred']} vs {row['bars_per_bar_truth']}  "
            f"n {row['n_beats']}/{row['truth_beats']} · {row['n_downbeats']}/{row['truth_downbeats']}"
        )

    summary = {
        "engine": args.engine,
        "rows": rows,
        "mean_beat_f": round(statistics.mean(row["beat_f"] for row in rows), 3) if rows else 0,
        "mean_downbeat_f": round(statistics.mean(row["downbeat_f"] for row in rows), 3) if rows else 0,
    }
    out = REPO / "bench" / "reports" / "phase-4" / "beats.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1) + "\n")
    print(f"\nmean beat F {summary['mean_beat_f']}, mean downbeat F {summary['mean_downbeat_f']}")
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
