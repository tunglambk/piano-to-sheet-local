"""L3 metric: OMR-NED via VeroSim (D-022)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from p2s.core.config import REPO_ROOT

VEROSIM = REPO_ROOT / "data" / "datasets" / "verosim" / "build" / "verosim"


def available() -> bool:
    return VEROSIM.exists()


def omr_ned(pred: Path, gt: Path, timeout: int = 900) -> float | None:
    """Return OMR-NED ×100, or None when the pair cannot be scored."""
    if not available():
        return None
    proc = subprocess.run(
        [str(VEROSIM), str(pred), str(gt)], capture_output=True, text=True, timeout=timeout, check=False
    )
    if proc.returncode != 0:
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
    if not payload.get("ok"):
        return None
    return float(payload["omr_ned"]) * 100.0
