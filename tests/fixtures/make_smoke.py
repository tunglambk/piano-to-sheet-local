#!/usr/bin/env python3
"""Synthesise the licence-safe smoke clip used by the contract tests.

A pure sine (what CI used to generate) carries no notes and no pulse, so the AMT
and beat engines legitimately returned nothing and the GPU contract tests failed.
This renders a short two-octave C-major scale with decaying harmonics at 120 BPM,
which is enough for a transcription model to find notes and for a tracker to find
beats — and it is generated, so it carries no licence.

    python tests/fixtures/make_smoke.py [output.wav]
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import soundfile

SAMPLE_RATE = 44100
TEMPO_BPM = 120.0
NOTE_S = 60.0 / TEMPO_BPM / 2  # eighth notes
SCALE = [60, 62, 64, 65, 67, 69, 71, 72, 71, 69, 67, 65, 64, 62, 60, 60]
HARMONICS = ((1.0, 1.0), (2.0, 0.35), (3.0, 0.15), (4.0, 0.08))


def _note(freq: float, duration: float) -> np.ndarray:
    times = np.arange(int(duration * SAMPLE_RATE)) / SAMPLE_RATE
    envelope = np.exp(-3.0 * times / duration) * (1.0 - np.exp(-400.0 * times))
    signal = np.zeros_like(times)
    for ratio, amplitude in HARMONICS:
        signal += amplitude * np.sin(2 * np.pi * freq * ratio * times)
    return signal * envelope


def render(path: Path) -> Path:
    audio = np.zeros(int(len(SCALE) * NOTE_S * SAMPLE_RATE + SAMPLE_RATE * 0.5))
    for index, midi in enumerate(SCALE):
        freq = 440.0 * 2 ** ((midi - 69) / 12)
        start = int(index * NOTE_S * SAMPLE_RATE)
        piece = _note(freq, NOTE_S * 1.8)
        audio[start : start + len(piece)] += piece[: max(0, len(audio) - start)]
    peak = float(np.max(np.abs(audio))) or 1.0
    audio = 0.6 * audio / peak
    stereo = np.repeat(audio[:, None], 2, axis=1).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    soundfile.write(path, stereo, SAMPLE_RATE)
    return path


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "data/fixtures/smoke/fast_passage.wav")
    print(render(target))
