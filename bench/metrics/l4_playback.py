"""L4 playback fidelity: render the score, compare its chroma with the recording.

The score is rendered offline (MusicXML -> MIDI -> FluidSynth with a piano
soundfont), then both signals are reduced to chroma frames and aligned with DTW.
The score is reported as `1 - mean cosine distance` along the warping path, so a
perfect match is 1.0 and a wrong score is clearly lower (spec §6.4).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050
FRAME = 2048
HOP = 512
PITCH_CLASSES = 12


def _find_fluidsynth() -> str | None:
    """PATH first, then the repository's own environment (the CPU env ships it)."""
    import os

    override = os.environ.get("P2S_FLUIDSYNTH")
    if override and Path(override).exists():
        return override
    found = shutil.which("fluidsynth")
    if found:
        return found
    repo = Path(__file__).resolve().parents[2]
    for candidate in (repo / ".envs" / "base" / "bin" / "fluidsynth", repo / ".tools" / "fluidsynth"):
        if candidate.exists():
            return str(candidate)
    return None


def _soundfont() -> Path | None:
    try:
        import pretty_midi

        candidate = Path(pretty_midi.__file__).parent / "TimGM6mb.sf2"
        return candidate if candidate.exists() else None
    except ImportError:
        return None


def score_to_midi(musicxml: bytes, out_midi: Path) -> bool:
    from music21 import converter

    with tempfile.NamedTemporaryFile(suffix=".musicxml", delete=False) as handle:
        handle.write(musicxml)
        path = Path(handle.name)
    try:
        score = converter.parse(str(path))
        score.write("midi", fp=str(out_midi))
        return out_midi.exists()
    except Exception:  # noqa: BLE001 - an unreadable score is a zero, not a crash
        return False
    finally:
        path.unlink(missing_ok=True)


def render_midi(midi: Path, out_wav: Path) -> bool:
    fluidsynth = _find_fluidsynth()
    soundfont = _soundfont()
    if fluidsynth is None or soundfont is None:
        return False
    result = subprocess.run(
        [fluidsynth, "-ni", "-F", str(out_wav), "-r", str(SAMPLE_RATE), str(soundfont), str(midi)],
        capture_output=True,
        check=False,
        timeout=300,
    )
    return result.returncode == 0 and out_wav.exists()


def chroma(path: Path) -> np.ndarray:
    import soundfile

    data, rate = soundfile.read(path, dtype="float32", always_2d=True)
    mono = data.mean(axis=1)
    if len(mono) < FRAME:
        return np.zeros((0, PITCH_CLASSES))
    frames = np.lib.stride_tricks.sliding_window_view(mono, FRAME)[::HOP]
    window = np.hanning(FRAME)
    spectrum = np.abs(np.fft.rfft(frames * window, axis=1))
    freqs = np.fft.rfftfreq(FRAME, d=1.0 / rate)
    with np.errstate(divide="ignore"):
        midi = np.round(69 + 12 * np.log2(np.maximum(freqs, 1e-6) / 440.0)).astype(np.int32)
    out = np.zeros((spectrum.shape[0], PITCH_CLASSES), dtype=np.float32)
    for index in range(PITCH_CLASSES):
        mask = (midi >= 21) & (midi <= 108) & (midi % PITCH_CLASSES == index)
        if mask.any():
            out[:, index] = spectrum[:, mask].sum(axis=1)
    norm = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.maximum(norm, 1e-9)


def _cosine_cost(a: np.ndarray, b: np.ndarray) -> float:
    if not np.any(a) or not np.any(b):
        return 0.0 if (not np.any(a) and not np.any(b)) else 1.0
    return float(1.0 - float(np.dot(a, b)))


def _normalise(features: np.ndarray) -> np.ndarray:
    norm = np.linalg.norm(features, axis=1, keepdims=True)
    return features / np.maximum(norm, 1e-9)


def _resample(features: np.ndarray, target: int = 600) -> np.ndarray:
    """Resample a chroma sequence to a fixed length so DTW only sees warp, not tempo."""
    if features.shape[0] <= 1:
        return features
    index = np.linspace(0, features.shape[0] - 1, target)
    low = np.floor(index).astype(int)
    high = np.minimum(low + 1, features.shape[0] - 1)
    weight = (index - low)[:, None]
    return features[low] * (1 - weight) + features[high] * weight


def chroma_dtw_similarity(a: np.ndarray, b: np.ndarray, band: int | None = None) -> float:
    """1 - mean cosine distance along a banded DTW path."""
    if a.size == 0 or b.size == 0:
        return 0.0
    a = _normalise(_resample(a))
    b = _normalise(_resample(b))
    n, m = len(a), len(b)
    band = band or max(40, int(0.3 * max(n, m)))
    inf = float("inf")
    cost = np.full((n + 1, m + 1), inf, dtype=np.float64)
    cost[0, 0] = 0.0
    for i in range(1, n + 1):
        low = max(1, i - band)
        high = min(m, i + band)
        for j in range(low, high + 1):
            step = min(cost[i - 1, j], cost[i, j - 1], cost[i - 1, j - 1])
            cost[i, j] = step + _cosine_cost(a[i - 1], b[j - 1])
    if not np.isfinite(cost[n, m]):
        return 0.0
    return float(max(0.0, 1.0 - cost[n, m] / max(n, m)))


def evaluate(musicxml: bytes, recording: Path, workdir: Path) -> dict[str, float | bool]:
    """Render the score and compare it with the recording."""
    midi = workdir / "l4.mid"
    wav = workdir / "l4.wav"
    if not score_to_midi(musicxml, midi):
        return {"similarity": 0.0, "rendered": False}
    if not render_midi(midi, wav):
        return {"similarity": 0.0, "rendered": False}
    score_chroma = chroma(wav)
    reference_chroma = chroma(recording)
    return {"similarity": round(chroma_dtw_similarity(score_chroma, reference_chroma), 4), "rendered": True}
