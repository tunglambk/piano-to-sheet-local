"""L4 playback fidelity metric (bench wrapper around `p2s.render.playback`)."""

from __future__ import annotations

from p2s.render.playback import (  # noqa: F401  (re-exported for the benchmark)
    chroma,
    chroma_dtw_similarity,
    evaluate,
    render_midi,
    score_to_midi,
)
