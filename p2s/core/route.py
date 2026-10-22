"""S1 — route and quality warnings (spec §3).

Phase 1 has no source separation: everything is labelled `solo_piano`. The stage
still inspects the decoded audio and emits quality warnings that the UI shows and
the manifest records (clipping, low sample rate, long silence).
"""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from p2s.core.schemas import AudioRef

CLIP_THRESHOLD = 0.999
SILENCE_DBFS = -60.0


class RouteDecision(BaseModel):
    label: str = "solo_piano"
    warnings: list[str] = Field(default_factory=list)
    clipping_ratio: float = 0.0
    silence_ratio: float = 0.0
    peak_dbfs: float = -120.0


def route(audio: AudioRef) -> RouteDecision:
    import soundfile as sf

    data, sr = sf.read(audio.path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1) if data.ndim == 2 else data
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    clipped = float(np.mean(np.abs(mono) >= CLIP_THRESHOLD)) if mono.size else 0.0
    frame = max(1, int(sr * 0.05))
    usable = (mono.size // frame) * frame
    if usable:
        frames = mono[:usable].reshape(-1, frame)
        rms = np.sqrt(np.mean(frames**2, axis=1))
        silent = float(np.mean(rms < 10 ** (SILENCE_DBFS / 20))) if rms.size else 0.0
    else:
        silent = 1.0
    warnings: list[str] = []
    if clipped > 0.001:
        warnings.append(f"audio clips on {clipped * 100:.2f}% of samples; notes may be spurious")
    if sr < 22050:
        warnings.append(f"low sample rate ({sr} Hz); transcription quality may drop")
    if silent > 0.5:
        warnings.append(f"{silent * 100:.0f}% of the audio is silent")
    return RouteDecision(
        label="solo_piano",
        warnings=warnings,
        clipping_ratio=round(clipped, 6),
        silence_ratio=round(silent, 6),
        peak_dbfs=round(20 * float(np.log10(peak)) if peak > 0 else -120.0, 2),
    )
