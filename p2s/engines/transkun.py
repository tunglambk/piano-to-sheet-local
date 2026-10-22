"""S3 — Transkun v2 (in-process, MIT code; checkpoint license not stated — D-019)."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from p2s.core.config import EngineSpec, ModelLockEntry
from p2s.core.schemas import AMTOptions, AudioRef, NoteEvent, Performance
from p2s.core.weights import maybe_verify
from p2s.engines.base import EngineBase


def _package_weight() -> Path:
    import transkun

    return Path(transkun.__file__).parent / "pretrained" / "2.0.pt"


class TranskunEngine(EngineBase):
    def __init__(self, spec: EngineSpec, lock: ModelLockEntry, device: str = "cuda") -> None:
        super().__init__("transkun_v2", spec, lock, device)
        self._model = None

    def _load(self) -> None:
        import torch
        from moduleconf import parseFromFile

        weight = _package_weight()
        maybe_verify(self.lock, weight)
        conf_path = weight.with_suffix(".conf")
        manager = parseFromFile(str(conf_path))
        factory = manager["Model"].module.TransKun  # type: ignore[union-attr]
        self._model = factory(conf=manager["Model"].config)
        checkpoint = torch.load(weight, map_location="cpu", weights_only=False)
        state = checkpoint.get("best_state_dict") or checkpoint["state_dict"]
        self._model.load_state_dict(state, strict=False)
        self._model = self._model.to(self.device).eval()
        torch.set_grad_enabled(False)

    def _close(self) -> None:
        self._model = None
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass

    def _version(self) -> str:
        import torch

        return f"2.0.1+torch{torch.__version__}"

    def _weights(self) -> dict[str, str]:
        return {
            "pretrained/2.0.pt": next(
                iter(w.get("sha256", "") for w in self.lock.weights if "2.0.pt" in w.get("file", "")), ""
            )
        }

    def transcribe(self, audio: AudioRef, opts: AMTOptions) -> Performance:
        import pydub
        import soxr
        import torch

        self.load()
        assert self._model is not None
        self._model = self._model.to(opts.device)
        self.device = opts.device
        segment = pydub.AudioSegment.from_file(audio.path)
        samples = (
            np.array(segment.get_array_of_samples()).reshape(-1, segment.channels).astype(np.float32) / 2**15
        )
        if segment.frame_rate != self._model.fs:
            samples = soxr.resample(samples, segment.frame_rate, self._model.fs)
        tensor = torch.from_numpy(samples).to(opts.device)
        with torch.no_grad():
            raw = self._model.transcribe(tensor, discardSecondHalf=False)
        notes: list[NoteEvent] = []
        pedals: list[tuple[float, float]] = []
        offset = audio.origin_offset_s
        for note in raw:
            if note.pitch > 0:
                if (note.end - note.start) < opts.min_note_s:
                    continue
                notes.append(
                    NoteEvent(
                        pitch=int(note.pitch),
                        onset=offset + float(note.start),
                        offset=offset + float(note.end),
                        velocity=max(1, min(127, int(note.velocity))),
                    )
                )
            elif opts.with_pedal and int(note.pitch) == -64:
                pedals.append((offset + float(note.start), offset + float(note.end)))
        notes.sort(key=lambda n: (n.onset, n.pitch, n.offset))
        return Performance(notes=notes, pedals=pedals, engine=self.info())
