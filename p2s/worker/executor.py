"""Child process that runs one job through the Phase 1 pipeline (plan step 3).

Running every job in its own process is what makes cancel honest: the worker can
SIGTERM the whole group, the OS reclaims the GPU memory, and a crashed engine
cannot poison the long-lived server.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session

from p2s.core.config import load_config
from p2s.core.db import Artifact, Job, StageRun, emit, init_db, utcnow
from p2s.core.pipeline import Pipeline
from p2s.core.schemas import IngestOptions, MeterHints, ScoreOptions

ARTIFACT_KINDS = {
    "pdf": "score.pdf",
    "musicxml": "score.musicxml",
    "mxl": "score.mxl",
    "mei": "score.mei",
    "timemap": "timemap.json",
    "mid": "performance.mid",
    "mid_quantized": "quantized.mid",
}


def job_dir(data_dir: Path, job_id: str) -> Path:
    path = Path(data_dir) / "jobs" / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _options(job: Job) -> tuple[IngestOptions, ScoreOptions, MeterHints]:
    params = job.params()
    ingest = IngestOptions(**params.get("ingest", {}))
    score = ScoreOptions(**params.get("score", {}))
    hints = MeterHints(**params.get("hints", {}))
    selected = job.range()
    if selected:
        ingest = ingest.model_copy(
            update={"start_s": selected.get("start_s"), "end_s": selected.get("end_s")}
        )
    return ingest, score, hints


def run_job(job_id: str, data_dir: str) -> int:
    data = Path(data_dir)
    engine = init_db(data)
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if job is None:
            return 2
        preset, input_path = job.preset, Path(job.input_path)
        ingest, score, hints = _options(job)
        device = job.params().get("device") or None

    def progress(stage: str, status: str, info: dict) -> None:
        with Session(engine) as session:
            current = session.get(Job, job_id)
            if current is None:
                return
            payload = {"stage": stage, "status": status}
            payload.update({k: v for k, v in info.items() if isinstance(v, (str, int, float, bool))})
            emit(session, current, "stage", payload)
            session.commit()

    def cancel() -> bool:
        with Session(engine) as session:
            current = session.get(Job, job_id)
            return bool(current and current.cancel_requested)

    pipeline = Pipeline(load_config(), data, job_id=job_id, progress=progress, cancel=cancel, device=device)
    try:
        result = pipeline.run(input_path, preset, ingest, score, hints)
    except BaseException as exc:  # noqa: BLE001 - every failure must become a state
        with Session(engine) as session:
            current = session.get(Job, job_id)
            if current is not None:
                current.status = "cancelled" if cancel() else "failed"
                current.error = f"{type(exc).__name__}: {exc}"[:2000]
                current.updated_at = utcnow()
                emit(session, current, "end", {"status": current.status, "error": current.error})
                session.commit()
        return 1

    out = job_dir(data, job_id)
    (out / "manifest.json").write_text(json.dumps(result.manifest, sort_keys=True, indent=1) + "\n")
    cache = data / "cache"
    s0_key = result.stage_keys.get("s0_ingest", "")
    audio = cache / s0_key[:2] / s0_key / "audio.wav"

    with Session(engine) as session:
        for name, path in result.artifacts.items():
            if name.startswith("svg/"):
                kind, _, page = name.partition("/")
                _add_artifact(session, job_id, kind, path, page)
                continue
            kind = next((k for k, v in ARTIFACT_KINDS.items() if v == name), name.rsplit(".", 1)[0])
            _add_artifact(session, job_id, kind, path, name)
        if audio.exists():
            _add_artifact(session, job_id, "audio", audio, "audio.wav")
        _add_artifact(session, job_id, "manifest", out / "manifest.json", "manifest.json")

        for record in result.run["stages"]:
            session.add(
                StageRun(
                    job_id=job_id,
                    stage=record["stage"],
                    engine=record["engine"],
                    engine_version=record["engine_version"],
                    cache_key=record["key"],
                    cache_hit=record["cache"] == "hit",
                    status="done",
                    duration_s=float(record["duration_s"]),
                )
            )
        current = session.get(Job, job_id)
        if current is not None:
            current.status = "succeeded"
            current.error = None
            current.updated_at = utcnow()
            emit(session, current, "end", {"status": "succeeded", "warnings": result.warnings})
        session.commit()
    return 0


def _add_artifact(session: Session, job_id: str, kind: str, path: Path, name: str) -> None:
    path = Path(path)
    if not path.exists():
        return
    session.add(
        Artifact(
            job_id=job_id,
            kind=kind,
            name=name,
            path=str(path),
            size=path.stat().st_size,
            sha256="",
            revision_id=None,
        )
    )
