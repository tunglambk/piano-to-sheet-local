"""Weight resolution and verification (`models/`, `configs/models.lock`)."""

from __future__ import annotations

import os
from pathlib import Path

from p2s.core.cache import sha256_file
from p2s.core.config import REPO_ROOT, ModelLockEntry
from p2s.core.errors import WeightsError

MODELS_DIR = Path(os.environ.get("P2S_MODELS_DIR", REPO_ROOT / "models"))


def resolve_weight(entry: ModelLockEntry, file_name: str) -> Path:
    """Find a weight file under models/<engine>/ or raise WeightsError."""
    direct = MODELS_DIR / entry.id / file_name
    if direct.exists():
        return direct
    candidates = list(MODELS_DIR.glob(f"**/{Path(file_name).name}"))
    if candidates:
        return candidates[0]
    raise WeightsError(
        f"weights for {entry.id!r} are missing: expected {direct}. "
        "See docs/dev-setup.md; downloads arrive in Phase 5."
    )


def verify_weight(path: Path, expected_sha256: str) -> None:
    if not expected_sha256 or len(expected_sha256) != 64:
        raise WeightsError(f"models.lock has no valid sha256 for {path.name}")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise WeightsError(f"sha256 mismatch for {path.name}: expected {expected_sha256}, got {actual}")


def maybe_verify(entry: ModelLockEntry, path: Path) -> None:
    """Verify when the lock has a real hash; skip placeholder entries."""
    for weight in entry.weights:
        if Path(weight.get("file", "")).name == path.name:
            digest = weight.get("sha256", "")
            if len(digest) == 64:
                verify_weight(path, digest)
            return
