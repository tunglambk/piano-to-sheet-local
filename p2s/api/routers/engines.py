"""Engine catalogue and weight loading (spec §5.4, D-018)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Request

from p2s.core.config import load_config
from p2s.core.errors import WeightsError
from p2s.core.weights import MODELS_DIR, maybe_verify, resolve_weight

router = APIRouter(tags=["engines"])


def _sidecar_health(url: str | None) -> str:
    if not url:
        return "unknown"
    try:
        response = httpx.get(f"{url.rstrip('/')}/v1/health", timeout=1.5)
        return "ok" if response.status_code == 200 else "down"
    except httpx.HTTPError:
        return "down"


@router.get("/engines")
def list_engines(request: Request) -> dict[str, Any]:  # noqa: ARG001 - app state kept for symmetry
    config = load_config()
    entries: list[dict[str, Any]] = []
    for stage in ("amt", "beats", "score", "separate", "e2e"):
        for name in config.engines.names(stage):
            spec = config.engines.get(stage, name)
            lock = config.lock.by_id(name) or config.lock.by_id(name.removesuffix("_small"))
            status = "configured"
            if spec.kind == "sidecar":
                status = _sidecar_health(spec.url)
            pinned = (lock.model_extra or {}).get("pinned", {}) if lock else {}
            package = str(pinned.get("package", ""))
            version = (
                pinned.get("version")
                or (package.split("==")[-1].strip() if "==" in package else package)
                or next(
                    (w.get("version") for w in (lock.weights if lock else []) if w.get("version")), "unknown"
                )
                or "unknown"
            )
            entries.append(
                {
                    "stage": stage,
                    "id": name,
                    "kind": spec.kind,
                    "version": version,
                    "code_license": lock.code_license if lock else "unknown",
                    "weight_license": lock.weight_license if lock else "unknown",
                    "commercial_use": lock.commercial_use if lock else "unknown",
                    "status": status,
                }
            )
    return {"engines": entries, "models_dir": str(MODELS_DIR)}


@router.post("/engines/{engine_id}/weights")
def load_weights(engine_id: str, body: dict[str, Any]) -> dict[str, Any]:
    source = str(body.get("source", "folder"))
    if source == "download":
        # The download path is part of the release phase (D-018).
        return {"status": "not-implemented", "detail": "downloads arrive with the release phase"}
    config = load_config()
    lock = config.lock.by_id(engine_id)
    if lock is None:
        raise WeightsError(f"unknown engine {engine_id}")
    verified: list[str] = []
    missing: list[str] = []
    for weight in lock.weights:
        name = Path(weight.get("file", "")).name
        if not name:
            continue
        try:
            path = resolve_weight(lock, name)
            maybe_verify(lock, path)
            verified.append(str(path))
        except WeightsError:
            missing.append(name)
    return {"status": "ok" if not missing else "partial", "verified": verified, "missing": missing}
