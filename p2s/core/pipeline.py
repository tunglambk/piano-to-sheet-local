"""Pipeline DAG S0–S8 with content-addressed caching (spec §5.3, plan Step 4).

Every stage records engine identity, cache key and timing. A stage whose key is in
the cache is reused, so changing only S5 options re-runs S5–S8 and reuses S0–S4.
If the configured S5 engine fails (crash, timeout, unreachable sidecar) the rule
quantiser runs instead; the warning lands in the score and in the manifest
(NFR-04).
"""

from __future__ import annotations

import json
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from p2s import __version__
from p2s.core.cache import Cache, sha256_file
from p2s.core.config import Config
from p2s.core.determinism import setup as setup_determinism
from p2s.core.errors import Cancelled, EngineError, P2SError
from p2s.core.ingest import decode, ffmpeg_version
from p2s.core.manifest import build_manifest
from p2s.core.route import route as route_audio
from p2s.core.schemas import (
    AMTOptions,
    AudioRef,
    BeatGrid,
    IngestOptions,
    MeterHints,
    Performance,
    ScoreDoc,
    ScoreOptions,
)
from p2s.engines.registry import create_engine
from p2s.post.align import align, parse_score_notes
from p2s.post.s6 import postprocess
from p2s.render.midi import performance_midi, quantized_midi
from p2s.render.mxl import build_mxl
from p2s.render.pdf import render_pdf
from p2s.render.timemap import build_timemap
from p2s.render.verovio import render as render_pages

ProgressCallback = Callable[[str, str, dict[str, Any]], None]


@dataclass
class StageRecord:
    stage: str
    engine: str
    engine_version: str
    key: str
    hit: bool
    duration_s: float
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "engine": self.engine,
            "engine_version": self.engine_version,
            "key": self.key,
            "cache": "hit" if self.hit else "miss",
            "duration_s": round(self.duration_s, 3),
            "warnings": self.warnings,
        }


@dataclass
class JobResult:
    artifacts: dict[str, Path]
    manifest: dict[str, Any]
    run: dict[str, Any]
    warnings: list[str]
    stage_keys: dict[str, str]
    score: ScoreDoc | None = None

    def artifact(self, name: str) -> Path:
        if name not in self.artifacts:
            raise KeyError(f"no artifact {name!r}; have {sorted(self.artifacts)}")
        return self.artifacts[name]


def _transcribe(
    primary: Any, extra: list[Any], audio: AudioRef, options: AMTOptions, ensemble: Any
) -> Performance:
    """Run one or more AMT engines and merge them with the preset's vote policy."""
    first = primary.transcribe(audio, options)
    if not extra:
        return first
    from p2s.post.ensemble import merge

    others = [engine.transcribe(audio, options) for engine in extra]
    return merge(
        [first, *others],
        vote=getattr(ensemble, "vote", "keep_if_both_or_high_velocity"),
        tolerance_ms=getattr(ensemble, "onset_tolerance_ms", 50.0),
    )


class Pipeline:
    def __init__(
        self,
        config: Config,
        data_dir: Path,
        job_id: str = "job",
        progress: ProgressCallback | None = None,
        cancel: Callable[[], bool] | None = None,
        device: str | None = None,
    ) -> None:
        self.config = config
        self.data_dir = Path(data_dir)
        self.cache = Cache(self.data_dir / "cache")
        self.job_id = job_id
        self.progress = progress or (lambda *_: None)
        self.cancel = cancel or (lambda: False)
        self.device = device
        self.records: list[StageRecord] = []
        self.warnings: list[str] = []
        self.stage_keys: dict[str, str] = {}
        self.input_sha256 = ""
        self.engines: dict[str, Any] = {}
        setup_determinism(0)

    # ------------------------------------------------------------------ utils
    def _check_cancel(self) -> None:
        if self.cancel():
            raise Cancelled("job cancelled")

    def _emit(self, stage: str, status: str, **info: Any) -> None:
        self.progress(stage, status, info)

    def _stage(
        self,
        *,
        stage: str,
        engine_id: str,
        engine_version: str,
        weights: dict[str, str] | None,
        params: dict[str, Any],
        parents: list[str],
        producer: Callable[[Path, Path], dict[str, Any]],
    ) -> tuple[dict[str, Any], Path]:
        """Run or reuse one stage. Returns (payload, entry dir)."""
        key = self.cache.compute_key(
            input_sha256=self.input_sha256,
            stage=stage,
            engine_id=engine_id,
            engine_version=engine_version,
            weights_sha256=weights,
            params=params,
            parent_keys=[self.stage_keys[p] for p in parents],
        )
        started = time.perf_counter()
        entry = self.cache.get(key)
        if entry is not None:
            self._record(stage, engine_id, engine_version, key, True, time.perf_counter() - started)
            return json.loads(entry.read_bytes("payload.json")), entry.dir
        self._check_cancel()
        self._emit(stage, "running")
        tmp = self.cache.tempdir()
        try:
            payload = producer(tmp, self.cache.entry_dir(key))
            (tmp / "payload.json").write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n")
            published = self.cache.put_dir(key, tmp)
        finally:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        self._record(stage, engine_id, engine_version, key, False, time.perf_counter() - started)
        return payload, published.dir

    def _record(
        self,
        stage: str,
        engine: str,
        version: str,
        key: str,
        hit: bool,
        seconds: float,
        warnings: list[str] | None = None,
    ) -> None:
        record = StageRecord(stage, engine, version, key, hit, seconds, list(warnings or []))
        self.records.append(record)
        self.stage_keys[stage] = key
        self.warnings.extend(record.warnings)
        self._emit(stage, "hit" if hit else "done", key=key, seconds=round(seconds, 3))

    # -------------------------------------------------------------------- run
    def run(
        self,
        input_path: Path,
        preset_name: str,
        ingest_opts: IngestOptions | None = None,
        score_opts: ScoreOptions | None = None,
        hints: MeterHints | None = None,
    ) -> JobResult:
        preset = self.config.preset(preset_name)
        ingest_opts = ingest_opts or IngestOptions()
        score_opts = score_opts or ScoreOptions()
        hints = hints or MeterHints()
        input_path = Path(input_path)
        self.input_sha256 = sha256_file(input_path)
        amt_device = self.device or preset.amt_device or ("cuda" if preset_name != "fast" else "cpu")

        # ---- S0 ingest -----------------------------------------------------
        s0_engine_version = ffmpeg_version()

        def produce_s0(tmp: Path, final_dir: Path) -> dict[str, Any]:
            wav = tmp / "audio.wav"
            audio = decode(input_path, wav, ingest_opts)
            audio = audio.model_copy(update={"path": str(final_dir / "audio.wav")})
            return json.loads(audio.model_dump_json())

        payload, _ = self._stage(
            stage="s0_ingest",
            engine_id="ffmpeg",
            engine_version=s0_engine_version,
            weights={},
            params=ingest_opts.model_dump(mode="json"),
            parents=[],
            producer=produce_s0,
        )
        audio = AudioRef.model_validate(payload)

        # ---- S1 route ------------------------------------------------------
        payload, _ = self._stage(
            stage="s1_route",
            engine_id="p2s-route",
            engine_version="1",
            weights={},
            params={},
            parents=["s0_ingest"],
            producer=lambda tmp, final: route_audio(audio).model_dump(mode="json"),
        )
        self.warnings.extend(payload.get("warnings", []))

        # ---- S3 AMT --------------------------------------------------------
        ensemble_enabled = bool(getattr(preset.amt_ensemble, "enabled", False))
        ensemble_names = [name for name in getattr(preset.amt_ensemble, "engines", []) if name]
        amt_names = (
            ensemble_names if ensemble_enabled and ensemble_names else [name for name in preset.amt if name]
        ) or ["transkun_v2"]
        amt_engine = self.engines.get(amt_names[0]) or create_engine(
            self.config, "amt", amt_names[0], device=amt_device
        )
        self.engines[amt_names[0]] = amt_engine
        extra_engines = []
        ensemble_enabled = bool(getattr(preset.amt_ensemble, "enabled", False))
        for name in amt_names[1:] if ensemble_enabled else []:
            try:
                extra_engines.append(
                    self.engines.get(name) or create_engine(self.config, "amt", name, device=amt_device)
                )
            except Exception as exc:  # noqa: BLE001 - a missing second opinion must be visible, not silent
                self.warnings.append(f"amt ensemble degraded: {name} unavailable ({exc.__class__.__name__})")
        amt_info = amt_engine.info()
        amt_opts = AMTOptions(device=amt_device)  # type: ignore[arg-type]
        payload, _ = self._stage(
            stage="s3_amt",
            engine_id=amt_info.id,
            engine_version=amt_info.version,
            weights=amt_info.weights_sha256,
            params={
                **amt_opts.model_dump(mode="json"),
                # The engine list and vote policy change the output, so they belong
                # in the cache key; without them an ablation silently reuses the
                # ensemble's performance (found while measuring D-043).
                "engines": list(preset.amt),
                "vote": preset.amt_ensemble.model_dump(mode="json"),
            },
            parents=["s0_ingest"],
            producer=lambda tmp, final: _transcribe(
                amt_engine, extra_engines, audio, amt_opts, preset.amt_ensemble
            ).model_dump(mode="json"),
        )
        performance = Performance.model_validate(payload)

        # ---- S4 beats ------------------------------------------------------
        beats_engine = self.engines.get(preset.beats) or create_engine(self.config, "beats", preset.beats)
        self.engines[preset.beats] = beats_engine
        beats_info = beats_engine.info()
        payload, _ = self._stage(
            stage="s4_beats",
            engine_id=beats_info.id,
            engine_version=beats_info.version,
            weights=beats_info.weights_sha256,
            params=hints.model_dump(mode="json"),
            parents=["s0_ingest"],
            producer=lambda tmp, final: beats_engine.track(audio, hints).model_dump(mode="json"),
        )
        grid = BeatGrid.model_validate(payload)

        # ---- S5 score (fallback on engine failure) -------------------------
        score_name = preset.score
        score_engine = create_engine(self.config, "score", score_name)
        used_fallback = False
        try:
            score_info = score_engine.info()
        except P2SError as exc:
            self.warnings.append(f"{score_name} unavailable ({exc}); falling back to {preset.fallback_score}")
            score_name = preset.fallback_score
            score_engine = create_engine(self.config, "score", score_name)
            score_info = score_engine.info()
            used_fallback = True
        parents = ["s3_amt"] if score_name == "m2st" else ["s3_amt", "s4_beats"]
        params = score_opts.model_dump(mode="json")

        def produce_score(tmp: Path, final: Path) -> dict[str, Any]:
            return score_engine.build(performance, grid, score_opts).model_dump(mode="json")

        try:
            payload, _ = self._stage(
                stage="s5_score",
                engine_id=score_info.id,
                engine_version=score_info.version,
                weights=score_info.weights_sha256,
                params=params,
                parents=parents,
                producer=produce_score,
            )
        except EngineError as exc:
            if used_fallback:
                raise
            self.warnings.append(f"{score_name} failed ({exc}); used {preset.fallback_score}")
            score_name = preset.fallback_score
            score_engine = create_engine(self.config, "score", score_name)
            score_info = score_engine.info()
            payload, _ = self._stage(
                stage="s5_score_fallback",
                engine_id=score_info.id,
                engine_version=score_info.version,
                weights=score_info.weights_sha256,
                params=params,
                parents=["s3_amt", "s4_beats"],
                producer=produce_score,
            )
        score_stage = "s5_score_fallback" if "s5_score" not in self.stage_keys else "s5_score"
        score = ScoreDoc.model_validate(payload)
        self.warnings.extend(score.warnings)

        # ---- S4b grid choice: prefer the candidate whose bar count agrees with
        # the score's own measure count (D-039). Requires S5, so it runs here.
        from p2s.post.rebar import bar_count as _bar_count

        span_for_bars = max(audio.duration_s, max((note.offset for note in performance.notes), default=0.0))
        from xml.etree import ElementTree as _ET

        _part = _ET.fromstring(score.musicxml).find("part")
        score_measures = len(_part.findall("measure")) if _part is not None else 0
        chosen_grid = grid
        alternatives: list[tuple[str, Any]] = []
        for candidate_name in ("beat_dbn",):
            try:
                candidate = create_engine(self.config, "beats", candidate_name)
                alternative_grid = candidate.track(audio, hints)
                if alternative_grid.beats and alternative_grid.downbeats:
                    alternatives.append((candidate_name, alternative_grid))
            except Exception:  # noqa: BLE001 - an optional extra opinion may be absent
                continue
        if alternatives and score_measures:

            def _distance(value: BeatGrid) -> int:
                return abs(_bar_count(value, span_for_bars) - score_measures)

            best_name, best_grid = min(alternatives, key=lambda item: _distance(item[1]))
            if _distance(best_grid) + 1 < _distance(grid):
                chosen_grid = best_grid
                self.warnings.append(
                    f"beat grid switched to {best_name}: {_bar_count(best_grid, span_for_bars)} bars "
                    f"vs {score_measures} score measures (default gave {_bar_count(grid, span_for_bars)})"
                )
        if chosen_grid is not grid:

            def produce_grid_choice(tmp: Path, final: Path) -> dict[str, Any]:
                return chosen_grid.model_dump(mode="json")

            payload, _ = self._stage(
                stage="s4b_grid",
                engine_id=chosen_grid.engine.id if chosen_grid.engine else "grid-choice",
                engine_version=chosen_grid.engine.version if chosen_grid.engine else "1",
                weights={},
                params={"bars": _bar_count(chosen_grid, span_for_bars), "score_measures": score_measures},
                parents=["s4_beats", score_stage],
                producer=produce_grid_choice,
            )
            grid = BeatGrid.model_validate(payload)

        # ---- S6 post -------------------------------------------------------
        payload, _ = self._stage(
            stage="s6_post",
            engine_id="p2s-post",
            engine_version=__version__,
            weights={},
            params={},
            parents=[score_stage],
            producer=lambda tmp, final: postprocess(score).model_dump(mode="json"),
        )
        score = ScoreDoc.model_validate(payload)
        self.warnings.extend(score.warnings)

        # ---- S7 align ------------------------------------------------------
        def produce_align(tmp: Path, final: Path) -> dict[str, Any]:
            mapping, warnings = align(performance, score.musicxml, grid)
            return {"alignment": {k: list(v) for k, v in mapping.items()}, "warnings": warnings}

        payload, _ = self._stage(
            stage="s7_align",
            engine_id="p2s-align",
            engine_version=__version__,
            weights={},
            params={},
            parents=["s6_post", "s3_amt"],
            producer=produce_align,
        )
        alignment = {k: (float(v[0]), float(v[1])) for k, v in payload.get("alignment", {}).items()}
        score = score.model_copy(update={"alignment": alignment})
        self.warnings.extend(payload.get("warnings", []))
        align_stage = "s7_align"

        # ---- S7b rebar: cut the bars at the tracked downbeats ------------
        from p2s.post.rebar import rebar

        span = max(audio.duration_s, max((note.offset for note in performance.notes), default=0.0))
        rebased = rebar(score.musicxml, alignment, grid, duration_s=span)
        if rebased is not None:
            rebased_xml: bytes = rebased

            def produce_rebar(tmp: Path, final: Path) -> dict[str, Any]:
                return {"musicxml": rebased_xml.decode("utf-8")}

            payload, _ = self._stage(
                stage="s7b_rebar",
                engine_id="p2s-rebar",
                engine_version=__version__,
                weights={},
                params={},
                parents=["s7_align", "s4_beats"],
                producer=produce_rebar,
            )
            score = score.model_copy(
                update={"musicxml": payload["musicxml"].encode("utf-8"), "alignment": {}}
            )

            def produce_realign(tmp: Path, final: Path) -> dict[str, Any]:
                mapping, warnings = align(performance, score.musicxml, grid)
                return {"alignment": {k: list(v) for k, v in mapping.items()}, "warnings": warnings}

            payload, _ = self._stage(
                stage="s7c_align",
                engine_id="p2s-align",
                engine_version=__version__,
                weights={},
                params={"rebarred": True},
                parents=["s7b_rebar", "s3_amt"],
                producer=produce_realign,
            )
            score = score.model_copy(
                update={
                    "alignment": {
                        k: (float(v[0]), float(v[1])) for k, v in payload.get("alignment", {}).items()
                    }
                }
            )
            self.warnings.extend(payload.get("warnings", []))
            align_stage = "s7c_align"

        # ---- S8 render -----------------------------------------------------
        def produce_render(tmp: Path, final: Path) -> dict[str, Any]:
            return self._produce_render(tmp, score, performance, grid)

        payload, entry_dir = self._stage(
            stage="s8_render",
            engine_id="verovio",
            engine_version=f"6.x+post-{__version__}",
            weights={},
            params={"scale": 40, "pdf": preset.pdf},
            parents=["s6_post", align_stage],
            producer=produce_render,
        )
        artifacts = {name: entry_dir / name for name in payload["files"]}
        self._check_cancel()

        engine_infos = {"s3_amt": amt_info, "s4_beats": beats_info, "s5_score": score_info}
        manifest = build_manifest(
            preset=preset_name,
            params={
                "ingest": ingest_opts.model_dump(mode="json"),
                "score": score_opts.model_dump(mode="json"),
                "hints": hints.model_dump(mode="json"),
            },
            audio=audio,
            engines=engine_infos,
            stage_keys=self.stage_keys,
            warnings=self.warnings,
            versions={
                "ffmpeg": s0_engine_version,
                "verovio": payload.get("verovio", "unknown"),
                "musescore": payload.get("pdf_engine", "unknown"),
            },
        )
        run = {
            "job_id": self.job_id,
            "stages": [r.as_dict() for r in self.records],
            "cache": self.cache.stats(),
        }
        return JobResult(
            artifacts=artifacts,
            manifest=manifest,
            run=run,
            warnings=self.warnings,
            stage_keys=dict(self.stage_keys),
            score=score,
        )

    # ------------------------------------------------------------- render
    def _produce_render(
        self, tmp: Path, score: ScoreDoc, perf: Performance, grid: BeatGrid
    ) -> dict[str, Any]:
        rendered = render_pages(score.musicxml)
        (tmp / "score.musicxml").write_bytes(score.musicxml)
        (tmp / "score.mei").write_text(rendered.mei)
        (tmp / "score.mxl").write_bytes(build_mxl(score.musicxml))
        pages_dir = tmp / "svg"
        pages_dir.mkdir()
        names = [f"svg/page-{i:03d}.svg" for i in range(1, len(rendered.pages) + 1)]
        for name, svg in zip(names, rendered.pages, strict=False):
            (tmp / name).write_text(svg)
        pdf_result = render_pdf(score.musicxml, tmp / "score.pdf", rendered.pages)
        timemap = build_timemap(score.musicxml, score.alignment or {}, grid)
        (tmp / "timemap.json").write_text(json.dumps(timemap, sort_keys=True, indent=1) + "\n")
        (tmp / "performance.mid").write_bytes(performance_midi(perf, grid))
        (tmp / "quantized.mid").write_bytes(quantized_midi(parse_score_notes(score.musicxml), grid))
        self.warnings.extend(pdf_result.warnings)
        files = [
            "score.musicxml",
            "score.mei",
            "score.mxl",
            "score.pdf",
            "timemap.json",
            "performance.mid",
            "quantized.mid",
            *names,
        ]
        return {
            "files": files,
            "verovio": rendered.verovio_version,
            "pdf_engine": pdf_result.engine,
            "n_pages": len(rendered.pages),
            "n_notes": len(timemap["notes"]),
        }
