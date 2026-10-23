"""Sidecar HTTP contract (D-012): /v1/info, /v1/health, /v1/infer, /v1/cancel, /v1/unload.

The app factory takes an engine object that exposes `info()` and either
`build(performance, grid, options)` (S5) or `transcribe(audio, options)` (S3).
Payloads are the Pydantic models from `p2s.core.schemas`, so both sides validate
the same contract.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from p2s.core.schemas import AudioRef, BeatGrid, MeterHints, Performance, ScoreDoc, ScoreOptions


class InferRequest(BaseModel):
    request_id: str
    kind: str
    audio: AudioRef | None = None
    performance: Performance | None = None
    grid: BeatGrid | None = None
    options: dict[str, Any] = {}


class InferResponse(BaseModel):
    request_id: str
    status: str = "ok"
    score: ScoreDoc | None = None
    performance: Performance | None = None
    grid: BeatGrid | None = None
    error: str | None = None


def create_app(engine: Any) -> FastAPI:
    app = FastAPI(title="p2s sidecar", version="1.0")
    cancelled: set[str] = set()
    lock = threading.Lock()

    @app.get("/v1/info")
    def info() -> dict[str, Any]:
        return engine.info().model_dump()

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "engine": engine.info().id}

    @app.post("/v1/infer", response_model=InferResponse)
    def infer(request: InferRequest) -> InferResponse:
        with lock:
            if request.request_id in cancelled:
                cancelled.discard(request.request_id)
                return InferResponse(request_id=request.request_id, status="cancelled")
        try:
            if request.kind == "beats":
                result = engine.track(request.audio, MeterHints())
                return InferResponse(request_id=request.request_id, grid=result)
            if request.kind == "score":
                if request.performance is None or request.grid is None:
                    raise HTTPException(status_code=422, detail="score inference needs performance and grid")
                options = ScoreOptions(**request.options)
                doc = engine.build(request.performance, request.grid, options)
                return InferResponse(request_id=request.request_id, score=doc)
            if request.kind == "amt":
                if request.audio is None:
                    raise HTTPException(status_code=422, detail="amt inference needs audio")
                from p2s.core.schemas import AMTOptions

                options = AMTOptions(**request.options)
                perf = engine.transcribe(request.audio, options)
                return InferResponse(request_id=request.request_id, performance=perf)
            raise HTTPException(status_code=422, detail=f"unknown inference kind {request.kind!r}")
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - reported to the client
            return InferResponse(
                request_id=request.request_id, status="error", error=f"{type(exc).__name__}: {exc}"
            )

    @app.post("/v1/cancel/{request_id}")
    def cancel(request_id: str) -> dict[str, str]:
        with lock:
            cancelled.add(request_id)
        return {"status": "cancel-requested"}

    @app.post("/v1/unload")
    def unload() -> dict[str, str]:
        engine.close()
        return {"status": "unloaded"}

    return app
