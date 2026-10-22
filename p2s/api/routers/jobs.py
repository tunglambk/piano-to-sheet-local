"""Job endpoints: upload, list, status, events, cancel, delete, artifacts (spec §5.4)."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from sqlalchemy import desc
from sqlalchemy.sql import column
from sqlmodel import Session, select

from p2s.core.db import Artifact, Job, JobEvent, StageRun, emit, new_id, utcnow
from p2s.core.errors import InputTooLong, UnsupportedInput
from p2s.core.ingest import MAX_BYTES, MAX_DURATION_S, probe

router = APIRouter(tags=["jobs"])

TERMINAL = ("succeeded", "failed", "cancelled")


def _session(request: Request) -> Session:
    return Session(request.app.state.engine)


def _job_or_404(request: Request, job_id: str) -> Job:
    with _session(request) as session:
        job = session.get(Job, job_id)
    if job is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"unknown job {job_id}")
    return job


def _artifacts(request: Request, job_id: str) -> list[Artifact]:
    with _session(request) as session:
        return list(session.exec(select(Artifact).where(Artifact.job_id == job_id).order_by("id")).all())


@router.post("/jobs", status_code=201)
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    preset: str = Form("accurate"),
    params: str = Form("{}"),
    range_json: str = Form("{}", alias="range"),
    name: str = Form(""),
) -> dict[str, str]:
    data_dir: Path = request.app.state.data_dir
    job_id = new_id()
    job_dir = data_dir / "uploads" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    target = job_dir / (Path(file.filename or "input").name or "input")

    digest = hashlib.sha256()
    size = 0
    with target.open("wb") as handle:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                handle.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise InputTooLong(f"file exceeds the {MAX_BYTES // (1024 * 1024)} MB limit")
            digest.update(chunk)
            handle.write(chunk)
    if size == 0:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise UnsupportedInput("empty upload")

    try:
        info = probe(target, allow_long=True)
        if info.duration_s > MAX_DURATION_S + 0.5:
            selected = json.loads(range_json or "{}")
            if not selected:
                raise InputTooLong(
                    f"{info.duration_s / 60:.1f} min exceeds the 20-minute limit; send a range"
                )
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise

    options = json.loads(params or "{}")
    job = Job(
        id=job_id,
        name=(name or Path(target).stem)[:120],
        status="queued",
        preset=preset,
        params_json=json.dumps(options, sort_keys=True),
        range_json=json.dumps(json.loads(range_json or "{}"), sort_keys=True),
        input_sha256=digest.hexdigest(),
        input_path=str(target),
        duration_s=info.duration_s,
    )
    with _session(request) as session:
        session.add(job)
        emit(session, job, "queued", {"name": job.name, "duration_s": info.duration_s, "preset": preset})
        session.commit()
    return {"job_id": job_id}


@router.get("/jobs")
def list_jobs(
    request: Request,
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    q: str | None = Query(None),
) -> dict[str, Any]:
    with _session(request) as session:
        statement = select(Job).order_by(desc("id"))
        if q:
            statement = statement.where(column("name").contains(q))
        if cursor:
            statement = statement.where(Job.id < cursor)
        jobs = list(session.exec(statement.limit(limit)).all())
        artifacts = {
            job_id: [
                {"kind": a.kind, "name": a.name, "size": a.size}
                for a in session.exec(select(Artifact).where(Artifact.job_id == job_id)).all()
            ]
            for job_id in (job.id for job in jobs)
        }
    return {
        "jobs": [_job_payload(job, artifacts.get(job.id, []), stages=[]) for job in jobs],
        "next_cursor": jobs[-1].id if len(jobs) == limit else None,
    }


def _job_payload(job: Job, artifacts: list[dict[str, Any]], stages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": job.id,
        "name": job.name,
        "status": job.status,
        "preset": job.preset,
        "duration_s": job.duration_s,
        "origin_offset_s": job.origin_offset_s,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "params": job.params(),
        "range": job.range(),
        "artifacts": artifacts,
        "stages": stages,
    }


@router.get("/jobs/{job_id}")
def get_job(request: Request, job_id: str) -> dict[str, Any]:
    job = _job_or_404(request, job_id)
    with _session(request) as session:
        stages = [
            {
                "stage": s.stage,
                "engine": s.engine,
                "engine_version": s.engine_version,
                "status": s.status,
                "cache_hit": s.cache_hit,
                "duration_s": s.duration_s,
            }
            for s in session.exec(select(StageRun).where(StageRun.job_id == job_id).order_by("id")).all()
        ]
    artifacts = [{"kind": a.kind, "name": a.name, "size": a.size} for a in _artifacts(request, job_id)]
    return _job_payload(job, artifacts, stages)


@router.patch("/jobs/{job_id}")
def rename_job(request: Request, job_id: str, body: dict[str, Any]) -> dict[str, str]:
    _job_or_404(request, job_id)
    name = str(body.get("name", "")).strip()
    if name:
        with _session(request) as session:
            stored = session.get(Job, job_id)
            assert stored is not None
            stored.name = name[:120]
            stored.updated_at = utcnow()
            session.add(stored)
            session.commit()
    return {"status": "ok"}


@router.post("/jobs/{job_id}/cancel")
def cancel_job(request: Request, job_id: str) -> dict[str, str]:
    job = _job_or_404(request, job_id)
    requested = request.app.state.queue.request_cancel(job_id)
    if requested:
        with _session(request) as session:
            stored = session.get(Job, job_id)
            assert stored is not None
            emit(session, stored, "cancel", {})
            session.commit()
    return {"status": "cancel-requested" if requested else job.status}


@router.delete("/jobs/{job_id}")
def delete_job(request: Request, job_id: str) -> dict[str, str]:
    _job_or_404(request, job_id)
    data_dir: Path = request.app.state.data_dir
    with _session(request) as session:
        for model in (Artifact, StageRun, JobEvent):
            for row in session.exec(select(model).where(model.job_id == job_id)).all():
                session.delete(row)
        stored = session.get(Job, job_id)
        if stored is not None:
            session.delete(stored)
        session.commit()
    shutil.rmtree(data_dir / "uploads" / job_id, ignore_errors=True)
    shutil.rmtree(data_dir / "jobs" / job_id, ignore_errors=True)
    return {"status": "deleted"}


@router.get("/jobs/{job_id}/artifacts")
def list_artifacts(request: Request, job_id: str) -> dict[str, Any]:
    _job_or_404(request, job_id)
    return {
        "artifacts": [
            {
                "kind": a.kind,
                "name": a.name,
                "size": a.size,
                "url": f"/api/v1/jobs/{job_id}/artifacts/{a.kind}/{a.name}",
            }
            for a in _artifacts(request, job_id)
        ]
    }


def _pick(request: Request, job_id: str, kind: str, name: str | None) -> Artifact:
    candidates = [a for a in _artifacts(request, job_id) if a.kind == kind]
    if name:
        candidates = [a for a in candidates if a.name == name]
    if not candidates:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail=f"no artifact {kind}")
    return candidates[0]


@router.get("/jobs/{job_id}/artifacts/{kind}/{name}")
def download_named_artifact(request: Request, job_id: str, kind: str, name: str) -> FileResponse:
    return download_artifact(request, job_id, kind, name)


@router.get("/jobs/{job_id}/artifacts/{kind}")
def download_artifact(
    request: Request, job_id: str, kind: str, name: str | None = Query(None)
) -> FileResponse:
    artifact = _pick(request, job_id, kind, name)
    path = Path(artifact.path)
    if not path.exists():
        from fastapi import HTTPException

        raise HTTPException(status_code=410, detail="artifact file is gone")
    media = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if path.suffix == ".musicxml":
        media = "application/vnd.recordare.musicxml+xml"
    if path.suffix == ".mxl":
        media = "application/vnd.recordare.musicxml"
    if path.suffix == ".mid":
        media = "audio/midi"
    if path.suffix == ".json":
        media = "application/json"
    if path.suffix == ".svg":
        media = "image/svg+xml"
    return FileResponse(path, media_type=media, filename=artifact.name or path.name)


@router.get("/jobs/{job_id}/events")
def job_events(request: Request, job_id: str, last_event_id: str | None = None) -> StreamingResponse:
    _job_or_404(request, job_id)
    since = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0

    def stream() -> Iterator[str]:
        cursor = since
        idle = 0.0
        while True:
            with _session(request) as session:
                rows = list(
                    session.exec(
                        select(JobEvent)
                        .where(JobEvent.job_id == job_id, column("seq") > cursor)
                        .order_by("seq")
                    ).all()
                )
                stored = session.get(Job, job_id)
            for row in rows:
                if row.seq is not None:
                    cursor = row.seq
                payload = json.dumps(row.payload(), sort_keys=True)
                yield f"id: {row.seq}\nevent: {row.type}\ndata: {payload}\n\n"
            if stored is not None and stored.status in TERMINAL and not rows:
                yield "event: close\ndata: {}\n\n"
                return
            idle += 0.25
            if idle >= 15:
                idle = 0.0
                yield ": keep-alive\n\n"
            time.sleep(0.25)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}/sync")
def sync_payload(request: Request, job_id: str) -> JSONResponse:
    """Timemap plus SVG page index, everything the Workspace needs in one call."""

    _job_or_404(request, job_id)
    pages = [a for a in _artifacts(request, job_id) if a.kind == "svg"]
    timemap_art = next((a for a in _artifacts(request, job_id) if a.kind == "timemap"), None)
    timemap = (
        json.loads(Path(timemap_art.path).read_text())
        if timemap_art and Path(timemap_art.path).exists()
        else {}
    )
    return JSONResponse(
        {
            "timemap": timemap,
            "pages": [
                {"name": page.name, "url": f"/api/v1/jobs/{job_id}/artifacts/svg/{page.name}"}
                for page in pages
            ],
        }
    )
