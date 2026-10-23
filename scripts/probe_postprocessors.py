#!/usr/bin/env python3
"""Compare Beat This! postprocessors and measure an accent-based selector.

The default (`minimal`) postprocessor gets most downbeats right but doubles them
on some recordings; madmom's DBN fixes those recordings and loses the others. A
selector that prefers the candidate whose downbeats carry more onset energy picks
the better one on all five P2S-Open dev excerpts (mean downbeat F 0.904, against
0.855 for `minimal` and 0.682 for DBN).

DBN needs `madmom`, which does not build on Python 3.11. Run this with a Python
3.10 interpreter that has `madmom`, CPU `torch`, `torchaudio`, `beat_this` and
`soundfile`, and point MADMOM_SHIM_DIR at a directory holding `shim.py` (it
aliases the `collections` ABCs that madmom still imports).

    MADMOM_SHIM_DIR=/tmp/mm310 /tmp/mm310/bin/python scripts/probe_postprocessors.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, os.environ.get("MADMOM_SHIM_DIR", "/tmp/mm310"))
import numpy as np  # noqa: E402
import shim  # noqa: F401,E402  (collections.abc aliases madmom needs)
import soundfile  # noqa: E402
from beat_this.inference import File2Beats  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OPEN = REPO / "data" / "p2s_open" / "v0"
WEIGHTS = REPO / "models" / "beat_this" / "final0.ckpt"
TOLERANCE_S = 0.07
HOP_S = 0.01


def f_measure(predicted: list[float], truth: list[float]) -> float:
    if not predicted or not truth:
        return 0.0
    used = [False] * len(truth)
    hits = 0
    for value in predicted:
        best, best_cost = -1, TOLERANCE_S
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


def envelope(path: Path) -> list[float]:
    data, rate = soundfile.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    hop = max(1, int(rate * HOP_S))
    usable = (len(mono) // hop) * hop
    frames = mono[:usable].reshape(-1, hop)
    energy = np.sqrt((frames**2).mean(axis=1))
    return [float(value) for value in np.maximum(0.0, np.diff(energy, prepend=energy[0]))]


def contrast(env: list[float], beats: list[float], downbeats: list[float]) -> float:
    if not env or not beats or not downbeats:
        return 0.0

    def accent(times: list[float]) -> float:
        values = [env[min(len(env) - 1, max(0, int(round(t / HOP_S))))] for t in times]
        return sum(values) / len(values)

    base = accent(beats)
    return accent(downbeats) / base if base > 0 else 0.0


def main() -> int:
    index = json.loads((OPEN / "items.json").read_text())
    items = [entry for entry in index if entry["split"] == "dev"][:5]
    models = {dbn: File2Beats(checkpoint_path=str(WEIGHTS), device="cpu", dbn=dbn) for dbn in (False, True)}
    rows = []
    for entry in items:
        folder = REPO / entry["path"]
        meta = json.loads((folder / "meta.json").read_text())
        truth = meta["beats"]["downbeats"]
        env = envelope(folder / "audio.wav")
        candidates = {}
        for dbn, model in models.items():
            first, second = model(str(folder / "audio.wav"))
            first, second = list(first), list(second)
            beats, downbeats = (second, first) if set(first) <= set(second) else (first, second)
            candidates["dbn" if dbn else "minimal"] = {
                "contrast": round(contrast(env, beats, downbeats), 3),
                "downbeat_f": round(f_measure(downbeats, truth), 3),
            }
        picked = max(candidates.items(), key=lambda item: item[1]["contrast"])
        rows.append(
            {
                "item": entry["item_id"],
                "minimal": candidates["minimal"],
                "dbn": candidates["dbn"],
                "picked": picked[0],
                "picked_downbeat_f": picked[1]["downbeat_f"],
            }
        )
        print(
            f"{entry['item_id']:22} minimal {candidates['minimal']['contrast']:.3f}/"
            f"{candidates['minimal']['downbeat_f']:.2f}  dbn {candidates['dbn']['contrast']:.3f}/"
            f"{candidates['dbn']['downbeat_f']:.2f}  -> {picked[0]} {picked[1]['downbeat_f']:.2f}"
        )

    summary = {
        "rows": rows,
        "mean_minimal": round(statistics.mean(row["minimal"]["downbeat_f"] for row in rows), 3),
        "mean_dbn": round(statistics.mean(row["dbn"]["downbeat_f"] for row in rows), 3),
        "mean_selected": round(statistics.mean(row["picked_downbeat_f"] for row in rows), 3),
        "oracle": round(
            statistics.mean(max(row["minimal"]["downbeat_f"], row["dbn"]["downbeat_f"]) for row in rows), 3
        ),
    }
    out = REPO / "bench" / "reports" / "phase-4" / "postprocessors.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=1) + "\n")
    print(
        f"\nminimal {summary['mean_minimal']}, dbn {summary['mean_dbn']}, "
        f"selected {summary['mean_selected']} (oracle {summary['oracle']})"
    )
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
