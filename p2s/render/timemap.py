"""Timemap: score ids → original-file seconds (S7 output, FR-06)."""

from __future__ import annotations

import json
from pathlib import Path

from p2s.post.align import parse_score_notes


def _dense_measures(known: dict[int, float], total: int) -> list[tuple[int, float]]:
    """Every measure gets an onset, including measures with no aligned note.

    The Workspace highlights by measure, so a gap would make the highlight jump.
    Unknown measures are interpolated between their neighbours, and extrapolated
    with the median measure length at the edges.
    """
    if not known:
        return []
    total = max(total, max(known))
    points = sorted(known.items())
    if len(points) > 1:
        spacing = sorted(
            (points[i + 1][1] - points[i][1]) / (points[i + 1][0] - points[i][0])
            for i in range(len(points) - 1)
            if points[i + 1][0] > points[i][0]
        )
        step = spacing[len(spacing) // 2] if spacing else 2.0
    else:
        step = 2.0
    dense: list[tuple[int, float]] = []
    first_number, first_onset = points[0]
    for number in range(1, first_number):
        dense.append((number, first_onset - (first_number - number) * step))
    for index, (number, onset) in enumerate(points):
        dense.append((number, onset))
        if index + 1 < len(points):
            next_number, next_onset = points[index + 1]
            for skipped in range(number + 1, next_number):
                fraction = (skipped - number) / (next_number - number)
                dense.append((skipped, onset + fraction * (next_onset - onset)))
    last_number, last_onset = points[-1]
    for number in range(last_number + 1, total + 1):
        dense.append((number, last_onset + (number - last_number) * step))
    return dense


def build_timemap(musicxml: bytes, alignment: dict[str, tuple[float, float]]) -> dict:
    notes = parse_score_notes(musicxml)
    measures: dict[int, float] = {}
    total = 0
    for note in notes:
        total = max(total, note.measure)
        onset = alignment.get(note.note_id)
        if onset is None:
            continue
        current = measures.get(note.measure)
        measures[note.measure] = onset[0] if current is None else min(current, onset[0])
    filled: list[dict] = []
    previous = 0.0
    for number, onset in _dense_measures(measures, total):
        previous = max(previous, onset)
        filled.append({"measure": number, "onset_s": round(previous, 6)})
    return {
        "notes": {k: [round(v[0], 6), round(v[1], 6)] for k, v in sorted(alignment.items())},
        "measures": filled,
        "n_notes": len(alignment),
    }


def write_timemap(path: Path, musicxml: bytes, alignment: dict[str, tuple[float, float]]) -> dict:
    payload = build_timemap(musicxml, alignment)
    path.write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n")
    return payload
