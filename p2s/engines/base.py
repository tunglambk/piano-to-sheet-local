"""Engine base class: info(), lazy construction, close() (spec §5.2, plan §3)."""

from __future__ import annotations

import time

from p2s.core.config import EngineSpec, ModelLockEntry
from p2s.core.schemas import EngineInfo


class EngineBase:
    """Common behaviour for in-process engines.

    Construction is cheap; `load()` runs on first use. `close()` frees GPU memory.
    """

    def __init__(self, engine_id: str, spec: EngineSpec, lock: ModelLockEntry, device: str = "cpu") -> None:
        self.engine_id = engine_id
        self.spec = spec
        self.lock = lock
        self.device = device
        self._loaded = False
        self._load_s = 0.0

    # ------------------------------------------------------------- lifecycle
    def load(self) -> None:
        if self._loaded:
            return
        start = time.perf_counter()
        self._load()
        self._load_s = time.perf_counter() - start
        self._loaded = True

    def _load(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    @property
    def load_seconds(self) -> float:
        return self._load_s

    def close(self) -> None:
        self._close()
        self._loaded = False

    def _close(self) -> None:  # pragma: no cover - overridden
        return None

    # ----------------------------------------------------------------- info
    def info(self) -> EngineInfo:
        return EngineInfo(
            id=self.engine_id,
            version=self._version(),
            weights_sha256=self._weights(),
            code_license=self.lock.code_license,
            weight_license=self.lock.weight_license,
            commercial_use=self.lock.commercial_use,  # type: ignore[arg-type]
            device=self.device,
            kind="inprocess",
        )

    def _version(self) -> str:
        return "unknown"

    def _weights(self) -> dict[str, str]:
        return {w.get("file", "?"): w.get("sha256", "") for w in self.lock.weights}
