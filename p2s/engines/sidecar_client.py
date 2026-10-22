"""HTTP client for sidecar engines (D-012). Used by S3/S5 when a stage is remote."""

from __future__ import annotations

import contextlib
import uuid

import httpx

from p2s.core.errors import EngineError
from p2s.core.schemas import AMTOptions, AudioRef, BeatGrid, EngineInfo, Performance, ScoreDoc, ScoreOptions


class SidecarClient:
    def __init__(self, engine_id: str, base_url: str, timeout_s: float = 600.0) -> None:
        self.engine_id = engine_id
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._info: EngineInfo | None = None

    def info(self) -> EngineInfo:
        if self._info is None:
            try:
                response = httpx.get(f"{self.base_url}/v1/info", timeout=10.0)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise EngineError(
                    f"sidecar {self.engine_id} is unreachable at {self.base_url}: {exc}"
                ) from exc
            self._info = EngineInfo(**response.json())
        return self._info

    def health(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/v1/health", timeout=5.0)
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def close(self) -> None:
        with contextlib.suppress(httpx.HTTPError):
            httpx.post(f"{self.base_url}/v1/unload", timeout=10.0)
        self._info = None

    def _infer(self, payload: dict) -> dict:
        try:
            response = httpx.post(f"{self.base_url}/v1/infer", json=payload, timeout=self.timeout_s)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise EngineError(f"sidecar {self.engine_id} timed out after {self.timeout_s}s") from exc
        except httpx.HTTPError as exc:
            raise EngineError(f"sidecar {self.engine_id} failed: {exc}") from exc
        body = response.json()
        if body.get("status") == "cancelled":
            raise EngineError(f"sidecar {self.engine_id} cancelled the request")
        if body.get("status") == "error":
            raise EngineError(f"sidecar {self.engine_id}: {body.get('error')}")
        if body.get("schema_version") not in (None, "1.0"):
            raise EngineError(f"sidecar {self.engine_id} speaks schema {body.get('schema_version')}")
        return body

    def build(self, perf: Performance, grid: BeatGrid, options: ScoreOptions) -> ScoreDoc:
        body = self._infer(
            {
                "request_id": uuid.uuid4().hex,
                "kind": "score",
                "performance": perf.model_dump(mode="json"),
                "grid": grid.model_dump(mode="json"),
                "options": options.model_dump(mode="json"),
            }
        )
        return ScoreDoc.model_validate(body["score"])

    def transcribe(self, audio: AudioRef, options: AMTOptions) -> Performance:
        body = self._infer(
            {
                "request_id": uuid.uuid4().hex,
                "kind": "amt",
                "audio": audio.model_dump(mode="json"),
                "options": options.model_dump(mode="json"),
            }
        )
        return Performance.model_validate(body["performance"])

    def cancel(self, request_id: str) -> None:
        with contextlib.suppress(httpx.HTTPError):
            httpx.post(f"{self.base_url}/v1/cancel/{request_id}", timeout=5.0)
