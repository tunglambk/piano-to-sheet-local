"""Job manifest (NFR-05): deterministic, no timestamps."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from p2s import __version__
from p2s.core.config import REPO_ROOT
from p2s.core.schemas import AudioRef, EngineInfo


def git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        ).stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


def build_manifest(
    *,
    preset: str,
    params: dict[str, Any],
    audio: AudioRef,
    engines: dict[str, EngineInfo],
    stage_keys: dict[str, str],
    warnings: list[str],
    versions: dict[str, str],
) -> dict[str, Any]:
    return {
        "p2s_version": __version__,
        "git_commit": git_commit(),
        "preset": preset,
        "params": params,
        "input": {
            "sha256": audio.sha256,
            "duration_s": round(audio.duration_s, 6),
            "origin_offset_s": round(audio.origin_offset_s, 6),
            "sample_rate": audio.sample_rate,
            "channels": audio.channels,
        },
        "engines": {stage: info.model_dump() for stage, info in sorted(engines.items())},
        "stage_keys": dict(sorted(stage_keys.items())),
        "versions": dict(sorted(versions.items())),
        "warnings": sorted(set(warnings)),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    import json

    path.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n")
