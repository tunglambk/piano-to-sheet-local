"""`p2s` command line (Phase 1 plan, Step 11)."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from p2s import __version__
from p2s.core.config import REPO_ROOT, load_config
from p2s.core.errors import P2SError
from p2s.core.ingest import probe
from p2s.core.log import configure as configure_logging
from p2s.core.pipeline import Pipeline
from p2s.core.schemas import IngestOptions, MeterHints, ScoreOptions
from p2s.core.weights import MODELS_DIR

OUTPUT_FILES = [
    "score.musicxml",
    "score.mxl",
    "score.pdf",
    "score.mei",
    "timemap.json",
    "performance.mid",
    "quantized.mid",
]


def _data_dir(args: argparse.Namespace) -> Path:
    return Path(args.data_dir).expanduser() if args.data_dir else REPO_ROOT / "data"


def _copy_tree(src: Path, dst: Path, files: list[str]) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    for name in files:
        source = src / name
        if not source.exists():
            continue
        target = dst / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def cmd_transcribe(args: argparse.Namespace) -> int:
    configure_logging(args.log_level)
    config = load_config()
    config.preset(args.preset)
    input_path = Path(args.input).expanduser()
    output_dir = Path(args.output).expanduser()
    info = probe(input_path, allow_long=args.start is not None or args.end is not None)
    ingest = IngestOptions(start_s=args.start, end_s=args.end, normalize_loudness=not args.no_loudnorm)
    score_opts = ScoreOptions(
        quantize_grid=args.quantize_grid,
        allow_triplets=not args.no_triplets,
        key_hint=args.key,
        time_signature_hint=args.time_signature,
    )
    hints = MeterHints(bpm=args.bpm, time_signature=args.time_signature)
    if args.sidecar_m2st:
        # Local development without Docker: point the sidecar URL at a local server.
        entry = config.engines.engines["score"]["m2st"]
        entry.url = args.sidecar_m2st
    pipeline = Pipeline(config, _data_dir(args), job_id=input_path.stem, device=args.device)
    print(
        f"p2s {__version__}: {input_path.name} ({info.duration_s:.1f}s) preset={args.preset}", file=sys.stderr
    )
    result = pipeline.run(input_path, args.preset, ingest, score_opts, hints)
    output_dir.mkdir(parents=True, exist_ok=True)
    render_dir = result.artifact("score.musicxml").parent
    files = list(OUTPUT_FILES)
    svg_dir = render_dir / "svg"
    if svg_dir.exists():
        for page in sorted(svg_dir.glob("*.svg")):
            files.append(f"svg/{page.name}")
    _copy_tree(render_dir, output_dir, files)
    (output_dir / "manifest.json").write_text(json.dumps(result.manifest, sort_keys=True, indent=1) + "\n")
    (output_dir / "run.json").write_text(json.dumps(result.run, sort_keys=True, indent=1) + "\n")
    (output_dir / "warnings.txt").write_text("\n".join(result.warnings) + ("\n" if result.warnings else ""))
    for warning in result.warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"wrote {output_dir}/score.pdf and {output_dir}/score.musicxml", file=sys.stderr)
    return 0


def cmd_weights(args: argparse.Namespace) -> int:
    from p2s.core.weights import maybe_verify, resolve_weight

    config = load_config()
    failures = 0
    for entry in config.lock.entries:
        if entry.scope != "app" or not entry.weights:
            continue
        for weight in entry.weights:
            file_name = Path(weight.get("file", "")).name
            try:
                path = resolve_weight(entry, file_name)
                maybe_verify(entry, path)
                print(f"ok      {entry.id}/{file_name} -> {path}")
            except P2SError as exc:
                failures += 1
                print(f"missing {entry.id}/{file_name}: {exc}")
    print(f"weights dir: {MODELS_DIR}")
    return 0 if failures == 0 else 4


def cmd_cache(args: argparse.Namespace) -> int:
    from p2s.core.cache import Cache

    cache = Cache(_data_dir(args) / "cache")
    stats = cache.stats()
    print(json.dumps(stats, indent=1))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import threading

    import uvicorn

    from p2s.api.app import create_app
    from p2s.worker.worker import Worker

    configure_logging(args.log_level)
    data_dir = _data_dir(args)
    web_dist = REPO_ROOT / "apps" / "web" / "dist"
    app = create_app(data_dir, web_dist if web_dist.exists() else None)
    worker: Worker | None = None
    if not args.no_worker:
        worker = Worker(data_dir)
        thread = threading.Thread(target=worker.run, name="p2s-worker", daemon=True)
        thread.start()
    print(f"p2s {__version__}: serving on http://{args.host}:{args.port} (data: {data_dir})", file=sys.stderr)
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())
    finally:
        if worker is not None:
            worker.stop()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p2s", description="Piano audio → two-staff sheet music, locally.")
    parser.add_argument("--version", action="version", version=f"p2s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    transcribe = sub.add_parser("transcribe", help="run the full pipeline on one file")
    transcribe.add_argument("input")
    transcribe.add_argument("-o", "--output", required=True)
    transcribe.add_argument("--preset", default="accurate", choices=["accurate", "fast", "song"])
    transcribe.add_argument("--start", type=float, default=None)
    transcribe.add_argument("--end", type=float, default=None)
    transcribe.add_argument("--quantize-grid", default="1/16", choices=["1/8", "1/16", "1/32"])
    transcribe.add_argument("--no-triplets", action="store_true")
    transcribe.add_argument("--no-loudnorm", action="store_true")
    transcribe.add_argument("--key", default=None)
    transcribe.add_argument("--time-signature", default=None)
    transcribe.add_argument("--bpm", type=float, default=None)
    transcribe.add_argument("--device", default=None, choices=["cpu", "cuda"])
    transcribe.add_argument("--data-dir", default=None, help="data root (cache, registry)")
    transcribe.add_argument("--sidecar-m2st", default=None, help="M2ST sidecar base URL (local dev)")
    transcribe.add_argument("--log-level", default="INFO")
    transcribe.set_defaults(func=cmd_transcribe)

    weights = sub.add_parser("weights", help="inspect model weights")
    weights.add_argument("action", choices=["verify"])
    weights.add_argument("--data-dir", default=None)
    weights.set_defaults(func=cmd_weights)

    serve = sub.add_parser("serve", help="API, worker and web UI on one port")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--data-dir", default=None)
    serve.add_argument("--no-worker", action="store_true", help="serve the API only")
    serve.add_argument("--log-level", default="INFO")
    serve.set_defaults(func=cmd_serve)

    cache = sub.add_parser("cache", help="cache inspection")
    cache.add_argument("action", choices=["stats"])
    cache.add_argument("--data-dir", default=None)
    cache.set_defaults(func=cmd_cache)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except P2SError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
