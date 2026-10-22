#!/usr/bin/env python3
"""NFR-02 (time to result) and NFR-03 (peak memory) baseline (plan step 8).

Runs a 3-minute recording through a preset several times, records end-to-end and
per-stage seconds, peak RSS of this process and peak GPU memory (sampled from
nvidia-smi). Values are recorded, not optimised.

    python scripts/measure_nfr.py --preset fast --runs 3
    python scripts/measure_nfr.py --preset accurate --runs 3 --device cuda
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import threading
import time
from pathlib import Path

import psutil

from p2s.core.config import load_config
from p2s.core.pipeline import Pipeline

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "bench" / "reports" / "phase-2"


def gpu_usage(device: int) -> int | None:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits", "-i", str(device)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        return int(out.splitlines()[0])
    except (subprocess.SubprocessError, ValueError):
        return None


def pick_audio(limit_s: float = 180.0) -> Path:
    manifest = json.loads((REPO / "data" / "datasets" / "maestro-selection.json").read_text())
    for meta in manifest.values():
        if meta.get("role") == "smoke_validation":
            return REPO / meta["path"]
    raise SystemExit("no MAESTRO validation recording in the manifest")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preset", default="fast", choices=["fast", "accurate"])
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--data-dir", default=str(REPO / "data"))
    parser.add_argument("--device", default=None, choices=["cpu", "cuda"])
    parser.add_argument("--gpu-index", type=int, default=0)
    args = parser.parse_args()

    audio = pick_audio()
    config = load_config()
    process = psutil.Process()
    samples: list[int] = []
    stop = threading.Event()
    baseline_gpu = gpu_usage(args.gpu_index)
    # A fresh data directory makes run 1 cold (no cache) and runs 2+ warm.
    data_dir = Path(args.data_dir) / "cachebench" / f"{args.preset}-{int(time.time())}"

    def sample() -> None:
        while not stop.is_set():
            value = gpu_usage(args.gpu_index)
            if value is not None:
                samples.append(value)
            stop.wait(0.5)

    thread = threading.Thread(target=sample, daemon=True)
    thread.start()

    runs = []
    for index in range(args.runs):
        started = time.perf_counter()
        pipeline = Pipeline(config, data_dir, job_id=f"nfr-{index}", device=args.device)
        result = pipeline.run(audio, args.preset)
        seconds = time.perf_counter() - started
        rss = process.memory_info().rss / (1024**2)
        runs.append(
            {
                "seconds": round(seconds, 1),
                "rss_mb": round(rss),
                "stages": {record["stage"]: record["duration_s"] for record in result.run["stages"]},
            }
        )
        print(f"run {index + 1}: {seconds:.1f}s, RSS {rss:.0f} MB, artifacts ok={bool(result.artifacts)}")
    stop.set()
    thread.join(timeout=2)

    payload = {
        "preset": args.preset,
        "device": args.device or "preset default",
        "audio": str(audio.relative_to(REPO)),
        "runs": runs,
        "median_seconds": round(statistics.median(run["seconds"] for run in runs), 1),
        "cold_seconds": runs[0]["seconds"],
        "peak_rss_mb": max(run["rss_mb"] for run in runs),
        "gpu_baseline_mb": baseline_gpu,
        "peak_gpu_mb": (max(samples) - baseline_gpu) if samples and baseline_gpu is not None else None,
        "data_dir": str(data_dir.relative_to(REPO)) if data_dir.is_relative_to(REPO) else str(data_dir),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"nfr_{args.preset}.json"
    path.write_text(json.dumps(payload, indent=1) + "\n")
    print(json.dumps({k: v for k, v in payload.items() if k != "runs"}, indent=1))
    print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
