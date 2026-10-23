"""L4 chroma-DTW similarity on synthetic signals (no FluidSynth needed)."""

from __future__ import annotations

import numpy as np

from bench.metrics.l4_playback import chroma_dtw_similarity


def _chroma(pattern: list[int], frames: int = 40) -> np.ndarray:
    out = np.zeros((frames, 12), dtype=np.float32)
    for index, pitch_class in enumerate(pattern):
        out[index, pitch_class % 12] = 1.0
    return out


def test_identical_sequences_score_one() -> None:
    a = _chroma([0, 4, 7, 12, 7, 4])
    assert chroma_dtw_similarity(a, a) > 0.99


def test_time_warp_keeps_similarity_high() -> None:
    a = _chroma([0, 4, 7, 12, 7, 4])
    doubled = np.repeat(a, 2, axis=0)
    assert chroma_dtw_similarity(a, doubled) > 0.99


def test_independent_sequence_scores_lower() -> None:
    rng = np.random.default_rng(0)
    a = np.abs(rng.normal(size=(60, 12))).astype(np.float32)
    b = np.abs(rng.normal(size=(60, 12))).astype(np.float32)
    assert chroma_dtw_similarity(a, b) < 0.9


def test_empty_input_is_zero() -> None:
    assert chroma_dtw_similarity(np.zeros((0, 12)), np.zeros((5, 12))) == 0.0
