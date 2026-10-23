"""Beat sidecar with a DBN postprocessor (S4, D-037).

Beat This! ships two postprocessors: `minimal` (default, but it doubles the
downbeats on some recordings) and `dbn` (madmom's dynamic Bayesian network,
which fixes those and loses others). This sidecar runs both and returns the
candidate whose downbeats carry more onset energy — measured at 0.904 mean
downbeat F on the P2S-Open dev split, against 0.855 for `minimal` alone.

`madmom` builds only on Python 3.10 (it imports `collections.MutableSequence`),
so it cannot live in the core 3.11 environment; that is what makes this a
sidecar.

    MADMOM_SHIM_DIR=sidecars/beat_dbn .envs/beat_dbn/bin/python -m uvicorn \
        sidecars.beat_dbn.server:app --port 8003
"""

from __future__ import annotations

import collections
import collections.abc
import os
import sys
from pathlib import Path

for _name in ("MutableSequence", "MutableMapping", "Mapping", "Sequence", "Iterable", "Callable", "Set"):
    if not hasattr(collections, _name):
        setattr(collections, _name, getattr(collections.abc, _name))

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("MPLCONFIGDIR", str(REPO / ".cache" / "mpl"))

import numpy as np  # noqa: E402
import soundfile  # noqa: E402
from beat_this.inference import File2Beats  # noqa: E402

from p2s.core.schemas import AudioRef, BeatGrid, EngineInfo, MeterHints  # noqa: E402
from p2s.engines.sidecar_server import create_app  # noqa: E402

CHECKPOINT = Path(os.environ.get("P2S_BEAT_CHECKPOINT", str(REPO / "models" / "beat_this" / "final0.ckpt")))
HOP_S = 0.01


def _envelope(path: str) -> np.ndarray:
    data, rate = soundfile.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    hop = max(1, int(rate * HOP_S))
    usable = (len(mono) // hop) * hop
    frames = mono[:usable].reshape(-1, hop)
    energy = np.sqrt((frames**2).mean(axis=1))
    return np.maximum(0.0, np.diff(energy, prepend=energy[0]))


def _contrast(env: np.ndarray, beats: list[float], downbeats: list[float]) -> float:
    if env.size == 0 or not beats or not downbeats:
        return 0.0

    def accent(times: list[float]) -> float:
        values = [env[min(len(env) - 1, max(0, int(round(t / HOP_S))))] for t in times]
        return float(np.mean(values))

    base = accent(beats)
    return accent(downbeats) / base if base > 0 else 0.0


class BeatDBNEngine:
    def __init__(self) -> None:
        self._models = {
            dbn: File2Beats(checkpoint_path=str(CHECKPOINT), device="cpu", dbn=dbn) for dbn in (False, True)
        }

    def info(self) -> EngineInfo:

        return EngineInfo(
            id="beat_dbn",
            version="beat-this+dbn",
            weights_sha256={CHECKPOINT.name: "see configs/models.lock"},
            code_license="MIT (beat_this) + BSD (madmom)",
            weight_license="MIT",
            commercial_use="no",
            device="cpu",
            kind="sidecar",
        )

    def track(self, audio: AudioRef | None, _hints: MeterHints | None = None) -> BeatGrid:
        if audio is None:
            raise ValueError("beat_dbn needs an audio reference")
        env = _envelope(audio.path)
        best: tuple[float, list[float], list[float]] | None = None
        for model in self._models.values():
            first, second = model(audio.path)
            first, second = list(first), list(second)
            beats, downbeats = (second, first) if set(first) <= set(second) else (first, second)
            score = _contrast(env, beats, downbeats)
            if best is None or score > best[0]:
                best = (score, beats, downbeats)
        assert best is not None
        return BeatGrid(beats=best[1], downbeats=best[2], engine=self.info())


app = create_app(BeatDBNEngine())
