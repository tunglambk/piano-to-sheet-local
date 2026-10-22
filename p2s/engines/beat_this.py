"""S4 — Beat This! (in-process; final0 on GPU, small0 on CPU)."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from p2s.core.config import EngineSpec, ModelLockEntry
from p2s.core.errors import WeightsError
from p2s.core.schemas import AudioRef, BeatGrid, MeterHints
from p2s.core.weights import resolve_weight
from p2s.engines.base import EngineBase


def _infer_meter(downbeats: list[float], beats: list[float]) -> tuple[int, list[tuple[float, str]]]:
    if len(downbeats) < 2:
        return 4, []
    counts: Counter[int] = Counter()
    for i in range(1, len(downbeats)):
        lo, hi = downbeats[i - 1], downbeats[i]
        n = sum(1 for b in beats if lo - 1e-6 <= b < hi - 1e-6)
        if 2 <= n <= 12:
            counts[n] += 1
    if not counts:
        return 4, []
    beats_per_bar = counts.most_common(1)[0][0]
    return beats_per_bar, [(downbeats[0], f"{beats_per_bar}/4")]


class BeatThis(EngineBase):
    def __init__(
        self, spec: EngineSpec, lock: ModelLockEntry, device: str = "cuda", checkpoint: str = "final0"
    ) -> None:
        super().__init__("beat_this", spec, lock, device)
        self.checkpoint = checkpoint
        self._model = None
        self._weights_path: Path | None = None

    def _load(self) -> None:
        from beat_this.inference import File2Beats

        weight_file = f"{self.checkpoint}.ckpt"
        try:
            self._weights_path = resolve_weight(self.lock, weight_file)
        except WeightsError:
            self._weights_path = None  # package falls back to its download URL
        self._model = File2Beats(
            checkpoint_path=str(self._weights_path) if self._weights_path else self.checkpoint,
            device=self.device,
        )

    def _close(self) -> None:
        self._model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _version(self) -> str:
        import importlib.metadata as md

        try:
            return f"{md.version('beat-this')}+{self.checkpoint}"
        except md.PackageNotFoundError:
            return f"unknown+{self.checkpoint}"

    def _weights(self) -> dict[str, str]:
        return {
            w.get("file", "?"): w.get("sha256", "")
            for w in self.lock.weights
            if w.get("file", "").startswith(self.checkpoint)
        }

    def track(self, audio: AudioRef, hints: MeterHints) -> BeatGrid:
        self.load()
        assert self._model is not None
        first, second = self._model(audio.path)
        first, second = list(first), list(second)
        # Postprocessor returns (downbeats, beats); verify the subset relation.
        beats, downbeats = (second, first) if set(first) <= set(second) else (first, second)
        offset = audio.origin_offset_s
        beats = [offset + float(b) for b in beats]
        downbeats = [offset + float(d) for d in downbeats]
        beats_per_bar, time_sigs = _infer_meter(downbeats, beats)
        tempo: list[tuple[float, float]] = []
        if len(beats) >= 2:
            gaps = [b - a for a, b in zip(beats, beats[1:], strict=False) if b > a]
            if gaps:
                gaps_sorted = sorted(gaps)
                median = gaps_sorted[len(gaps_sorted) // 2]
                tempo.append((beats[0], round(60.0 / median, 3)))
        if hints.time_signature:
            time_sigs = [(downbeats[0] if downbeats else (beats[0] if beats else 0.0), hints.time_signature)]
        if hints.bpm:
            tempo = [(beats[0] if beats else 0.0, float(hints.bpm))]
        if not time_sigs:
            time_sigs = [(beats[0] if beats else 0.0, f"{beats_per_bar}/4")]
        return BeatGrid(
            beats=beats, downbeats=downbeats, time_signatures=time_sigs, tempo_bpm=tempo, engine=self.info()
        )
