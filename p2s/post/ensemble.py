"""Merge several AMT transcriptions into one performance (D-043).

Two models hear different notes: an ensemble that keeps only what both agree on
removes hallucinations at the cost of recall, while keeping a high-velocity note
from either model preserves deliberate playing that only one model caught. The
vote policy names that trade-off; this module is the single place where it lives.
"""

from __future__ import annotations

from p2s.core.schemas import NoteEvent, Performance

DEFAULT_TOLERANCE_S = 0.05
HIGH_VELOCITY = 100


def _match(primary: list[NoteEvent], other: list[NoteEvent], tolerance: float) -> list[NoteEvent]:
    kept: list[NoteEvent] = []
    used = [False] * len(other)
    for note in primary:
        hit = False
        for index, candidate in enumerate(other):
            if used[index] or candidate.pitch != note.pitch:
                continue
            if abs(candidate.onset - note.onset) <= tolerance:
                used[index] = True
                hit = True
                break
        if hit:
            kept.append(note)
    return kept


def merge(
    performances: list[Performance],
    *,
    vote: str = "keep_if_both_or_high_velocity",
    tolerance_ms: float = DEFAULT_TOLERANCE_S * 1000,
) -> Performance:
    if not performances:
        raise ValueError("ensemble needs at least one performance")
    if len(performances) == 1:
        return performances[0]
    tolerance = tolerance_ms / 1000.0
    reference = performances[0]
    notes: list[NoteEvent] = []
    for other in performances[1:]:
        agreed = _match(reference.notes, other.notes, tolerance)
        if vote == "intersection":
            notes = agreed
        else:
            extra = [
                note
                for note in other.notes
                if note.velocity >= HIGH_VELOCITY
                and not any(
                    abs(note.onset - kept.onset) <= tolerance and note.pitch == kept.pitch for kept in agreed
                )
            ]
            notes = agreed + extra
        reference = reference.model_copy(update={"notes": notes})
    return reference.model_copy(
        update={
            "notes": sorted(notes, key=lambda note: (note.onset, note.pitch)),
            "engine": performances[0].engine,
        }
    )
