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


SPLITS = REPO_ROOT / "bench" / "splits" / "p2s_open_v0.json"


def _items(suite: str, limit: int, condition: str | None = None) -> list[dict]:
    if suite.startswith("p2s_open"):
        index = json.loads((P2S_OPEN / "items.json").read_text())
        split = "dev" if suite.endswith("dev") else "test"
        if SPLITS.exists():
            manifest = json.loads(SPLITS.read_text())
            allowed = set(manifest.get(split, []))
            items = [e for e in index if e["item_id"] in allowed]
        else:
            items = [e for e in index if e["split"] == split]
        if not items:
            raise P2SError(
                f"no P2S-Open items for split {split!r} in {SPLITS.name}: the frozen manifest has "
                f"{len(json.loads(SPLITS.read_text()).get(split, []))} entries (D-010)"
            )
        out = []
        for entry in items:
            item_dir = REPO_ROOT / entry["path"]
            meta_path = item_dir / "meta.json"
            meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
            out.append(
                {
                    "id": entry["item_id"],
                    "audio": item_dir / "audio.wav",
                    "gt_score": item_dir / "score.musicxml",
                    "gt_performance": item_dir / "performance.mid",
                    "start_s": float(entry.get("start_s") or meta.get("start_s") or 0.0),
                    "duration_s": float(meta.get("duration_s") or 0.0),
                    "condition": entry["condition"],
                }
            )
        if condition:
            out = [entry for entry in out if entry["condition"] == condition]
        return out[:limit] if limit else out
    raise P2SError(f"unknown suite {suite!r} (Phase 1 knows p2s_open_dev and p2s_open_test)")


def _run_preset(
    item: dict, preset: str, sidecar: str | None, device: str | None = None
) -> tuple[Path, Path] | None:
    from p2s.core.config import load_config
    from p2s.core.pipeline import Pipeline

    config = load_config()
    if sidecar:
        config.engines.engines["score"]["m2st"].url = sidecar
    pipeline = Pipeline(config, DATA, job_id=item["id"], device=device)
    result = pipeline.run(item["audio"], preset)
    return result.artifact("score.musicxml"), result.artifact("performance.mid")


def _run_baseline(item: dict) -> tuple[Path, Path] | None:
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
    return (out, midi) if to_musicxml(midi, out) else None


def _extra_metrics(item: dict, produced: tuple[Path, Path] | None) -> tuple[dict, float | None]:
    """L2 against the item's own performance, L4 against the item's recording.

    Both references belong to the item, never to the system under test: the
    reference performance ships with P2S-Open (`performance.mid`) and the
    recording with the item (`audio.wav`).
    """
    if produced is None:
        return {}, None
    musicxml, performance_mid = produced
    note_scores: dict = {}
    reference_midi = Path(item.get("gt_performance") or "")
    start_s = float(item.get("start_s") or 0.0)
    try:
        from bench.metrics.l2_notes import evaluate as note_evaluate

        reference = _performance_from_midi(
            reference_midi, start_s=start_s, duration_s=float(item.get("duration_s") or 0.0) or None
        )
        predicted = _performance_from_midi(performance_mid)
        if reference is not None and predicted is not None:
            note_scores = note_evaluate(predicted, reference)
    except Exception:  # noqa: BLE001 - a missing reference is a gap, not a crash
        note_scores = {}
    playback = None
    try:
        import tempfile

        from bench.metrics.l4_playback import evaluate as playback_evaluate

        if musicxml is not None:
            with tempfile.TemporaryDirectory() as tmp:
                playback = playback_evaluate(musicxml.read_bytes(), Path(item["audio"]), Path(tmp))[
                    "similarity"
                ]
    except Exception:  # noqa: BLE001 - rendering is optional
        playback = None
    return note_scores, playback


def _performance_from_midi(path: Path, start_s: float = 0.0, duration_s: float | None = None):
    """Read a MIDI file as a Performance (same shape the pipeline produces)."""
    import pretty_midi

    from p2s.core.schemas import EngineInfo, NoteEvent, Performance

    try:
        midi = pretty_midi.PrettyMIDI(str(path))
    except Exception:  # noqa: BLE001 - a broken reference is a gap, not a crash
        return None
    # P2S-Open items are excerpts of a longer performance: the reference MIDI has
    # to be cropped to the item window and rebased to zero before comparing.
    notes = [
        NoteEvent(
            pitch=int(note.pitch),
            onset=float(note.start - start_s),
            offset=float(note.end - start_s),
            velocity=int(note.velocity),
        )
        for instrument in midi.instruments
        for note in instrument.notes
        if note.start - start_s >= -1e-6 and (duration_s is None or note.start - start_s < duration_s)
    ]
    if not notes:
        return None
    return Performance(
        notes=notes,
        engine=EngineInfo(
            id="midi-file",
            version="1",
            weights_sha256={},
            code_license="n/a",
            weight_license="n/a",
            commercial_use="yes",
            device="cpu",
            kind="inprocess",
        ),
    )


def cmd_run(args: argparse.Namespace) -> int:
    from bench.metrics.l3_omrned import omr_ned
    from bench.stats import summarize

    if args.split == "test" and not args.final:
        raise P2SError("test-split runs need --final (D-010)")
    items = _items(args.suite, args.limit, getattr(args, "condition", None))
    RESULTS.mkdir(parents=True, exist_ok=True)
    values: dict[str, float | None] = {}
    rows = []
    for index, item in enumerate(items, start=1):
        started = time.perf_counter()
        try:
            if args.system.startswith("p2s"):
                preset = args.system.split(":", 1)[1] if ":" in args.system else "accurate"
                produced = _run_preset(item, preset, args.sidecar, args.device)
            else:
                produced = _run_baseline(item)
            musicxml = produced[0] if produced else None
            value = omr_ned(musicxml, item["gt_score"]) if musicxml else None
            status = "ok" if value is not None else "fail"
            note_scores, playback = _extra_metrics(item, produced)
        except P2SError as exc:
            value, status = None, f"error: {exc}"
        values[item["id"]] = value
        rows.append(
            {
                "id": item["id"],
                "condition": item.get("condition"),
                "status": status,
                "omr_ned": value,
                "note_f1": note_scores.get("note_f1"),
                "onset_f1": note_scores.get("onset_f1"),
                "playback": playback,
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
    run.add_argument("--condition", default=None, choices=["clean", "phone"])
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
