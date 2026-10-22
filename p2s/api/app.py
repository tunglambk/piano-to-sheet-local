"""FastAPI application (spec §5.4, plan step 4)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from p2s import __version__
from p2s.api.routers import engines, jobs
from p2s.core.db import init_db
from p2s.core.errors import P2SError
from p2s.worker.queue import SqliteQueue

STATUS_BY_ERROR = {
    "InputError": 400,
    "UnsupportedInput": 415,
    "CorruptInput": 422,
    "InputTooLong": 413,
    "ConfigError": 500,
    "WeightsError": 503,
    "EngineError": 503,
}


def create_app(data_dir: Path, web_dist: Path | None = None) -> FastAPI:
    data_dir = Path(data_dir)
    app = FastAPI(
        title="P2S Local", version=__version__, docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    app.state.data_dir = data_dir
    app.state.engine = init_db(data_dir)
    app.state.queue = SqliteQueue(app.state.engine)

    @app.exception_handler(P2SError)
    async def _p2s_error(_request: Request, exc: P2SError) -> JSONResponse:
        status = STATUS_BY_ERROR.get(type(exc).__name__, 500)
        return JSONResponse(
            status_code=status,
            content={"detail": str(exc), "code": type(exc).__name__, "exit_code": exc.exit_code},
        )

    @app.get("/api/v1/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(jobs.router, prefix="/api/v1")
    app.include_router(engines.router, prefix="/api/v1")
    if web_dist is not None and Path(web_dist).exists():
        dist = Path(web_dist)
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str) -> FileResponse:
            """Serve the built SPA; unknown paths fall back to index.html."""
            candidate = (dist / full_path).resolve()
            if full_path and str(candidate).startswith(str(dist.resolve())) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app
