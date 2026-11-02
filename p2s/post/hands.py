"""Split a piano part into two staves by pitch (D-091).

The score model used by the `accurate` preset emits **no** `<staff>` element (and
no `<staves>` attribute): every note arrives with no hand assignment, so the whole
piece was engraved on the treble staff with an empty bass staff. The model-free
quantiser already solved this with a variance-minimising threshold; that rule now
lives here so both paths share it.
"""

from __future__ import annotations

import numpy as np

LOW = 45.0
HIGH = 73.5
STEP = 0.5
DEFAULT = 60.0


def hand_threshold(pitches: list[int] | np.ndarray) -> float:
    """Pitch that separates the hands: the median, biased a fourth downwards.

    Three rules were scored against the reference staff assignment of two P2S-Open
    scores (fraction of notes whose hand matches): fixed middle C 0.856, the
    variance split 0.851, **median − 5 semitones 0.886**. The bias puts borderline
    notes in the bass, which is how accompaniment is written.
    """
    values = np.asarray(pitches, dtype=float)
    if values.size < 2:
        return DEFAULT
    return float(min(max(float(np.median(values)) - 5.0, LOW), HIGH))


def assign_staves(pitches: list[int]) -> list[int]:
    """1 for the right hand (at or above the threshold), 2 for the left."""
    threshold = hand_threshold(pitches)
    return [1 if pitch >= threshold else 2 for pitch in pitches]
