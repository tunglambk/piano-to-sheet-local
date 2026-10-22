"""`p2s-bench` — benchmark runner (Phase 1 skeleton; Parquet arrives in P3a)."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from p2s.core.config import REPO_ROOT
from p2s.core.errors import P2SError

DATA = REPO_ROOT / "data"
RESULTS = DATA / "bench" / "results"
P2S_OPEN = DATA / "p2s_open" / "v0"


def _items(suite: str, limit: int) -> list[dict]:
    if suite.startswith("p2s_open"):
        index = json.loads((P2S_OPEN / "items.json").read_text())
        split = "dev" if suite.endswith("dev") else "test"
        items = [e for e in index if e["split"] == split]
        if not items:
            raise P2SError(f"no P2S-Open items for split {split}")
        out = []
        for entry in items:
            item_dir = REPO_ROOT / entry["path"]
            out.append(
                {
                    "id": entry["item_id"],
                    "audio": item_dir / "audio.wav",
                    "gt_score": item_dir / "score.musicxml",
                    "condition": entry["condition"],
                }
            )
        return out[:limit] if limit else out
    raise P2SError(f"unknown suite {suite!r} (Phase 1 knows p2s_open_dev and p2s_open_test)")


def _run_preset(item: dict, preset: str, sidecar: str | None, device: str | None = None) -> Path | None:
    from p2s.core.config import load_config
    from p2s.core.pipeline import Pipeline

    config = load_config()
    if sidecar:
        config.engines.engines["score"]["m2st"].url = sidecar
    pipeline = Pipeline(config, DATA, job_id=item["id"], device=device)
    result = pipeline.run(item["audio"], preset)
    return result.artifact("score.musicxml")


def _run_baseline(item: dict) -> Path | None:
    import tempfile

    from bench.systems.transkun_musescore import to_musicxml
    from p2s.core.config import load_config
    from p2s.core.pipeline import Pipeline

    config = load_config()
    pipeline = Pipeline(config, DATA, job_id=f"baseline-{item['id']}")
    result = pipeline.run(item["audio"], "fast")
    midi = result.artifact("performance.mid")
    tmp = Path(tempfile.mkdtemp())
    out = tmp / "baseline.musicxml"
    return out if to_musicxml(midi, out) else None


def cmd_run(args: argparse.Namespace) -> int:
    from bench.metrics.l3_omrned import omr_ned
    from bench.stats import summarize

    if args.split == "test" and not args.final:
        raise P2SError("test-split runs need --final (D-010)")
    items = _items(args.suite, args.limit)
    RESULTS.mkdir(parents=True, exist_ok=True)
    values: dict[str, float | None] = {}
    rows = []
    for index, item in enumerate(items, start=1):
        started = time.perf_counter()
        try:
            if args.system.startswith("p2s"):
                preset = args.system.split(":", 1)[1] if ":" in args.system else "accurate"
                musicxml = _run_preset(item, preset, args.sidecar, args.device)
            else:
                musicxml = _run_baseline(item)
            value = omr_ned(musicxml, item["gt_score"]) if musicxml else None
            status = "ok" if value is not None else "fail"
        except P2SError as exc:
            value, status = None, f"error: {exc}"
        values[item["id"]] = value
        rows.append(
            {
                "id": item["id"],
                "condition": item.get("condition"),
                "status": status,
                "omr_ned": value,
                "seconds": round(time.perf_counter() - started, 1),
            }
        )
        print(f"[{index}/{len(items)}] {item['id']} {status} omr={value}", flush=True)
    summary = summarize(args.system, values)
    summary.update({"suite": args.suite, "split": args.split})
    out = RESULTS / f"{args.suite}_{args.system.replace(':', '_')}.json"
    out.write_text(json.dumps({"summary": summary, "items": rows}, indent=1) + "\n")
    print(json.dumps(summary, indent=1))
    print(f"wrote {out}")
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    paths = sorted(RESULTS.glob("*.json")) if not args.file else [Path(args.file)]
    for path in paths:
        payload = json.loads(path.read_text())
        summary = payload.get("summary", payload)
        print(f"{path.name}: {json.dumps(summary)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p2s-bench", description="P2S benchmark runner")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run one system on one suite")
    run.add_argument("--suite", required=True)
    run.add_argument("--system", required=True, help="p2s:accurate | p2s:fast | baseline:musescore")
    run.add_argument("--split", default="dev", choices=["dev", "test"])
    run.add_argument("--final", action="store_true")
    run.add_argument("--limit", type=int, default=0)
    run.add_argument("--sidecar", default="http://127.0.0.1:8002")
    run.add_argument("--device", default=None, choices=["cpu", "cuda"])
    run.set_defaults(func=cmd_run)

    summary = sub.add_parser("summary", help="print recorded summaries")
    summary.add_argument("--file", default=None)
    summary.set_defaults(func=cmd_summary)
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except P2SError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
