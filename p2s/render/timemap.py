"""Timemap: score ids → original-file seconds (S7 output, FR-06)."""

from __future__ import annotations

import json
from pathlib import Path

from p2s.core.schemas import BeatGrid
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


def _local_slope(pairs: list[tuple[float, float]], at: float) -> float:
    """Seconds per score beat near a beat position (median of nearby pairs)."""
    slopes = [
        (t2 - t1) / (b2 - b1)
        for (b1, t1), (b2, t2) in ((pairs[i], pairs[i + 1]) for i in range(len(pairs) - 1))
        if b2 > b1 and abs((b1 + b2) / 2 - at) <= 3
    ]
    if slopes:
        slopes.sort()
        return slopes[len(slopes) // 2]
    return 0.5


def _downbeat_onsets(downbeats: list[float], n_measures: int) -> list[tuple[int, float]] | None:
    """Spread the performance's downbeats over the score's measures.

    The engraver's bar count and the recording's bar count never match exactly
    (tempo and metre estimation differ by a few percent). When they are close,
    the downbeats are the better source of bar lines: every measure then starts
    on a real barline, which is what the user sees while playing (D-034).
    """
    if len(downbeats) < 4 or n_measures < 4:
        return None
    ratio = len(downbeats) / n_measures
    if not 0.85 <= ratio <= 1.18:
        return None
    if abs(len(downbeats) - n_measures) <= 2:
        # Close enough for a 1:1 mapping: proportional spreading would drift by a
        # whole bar at the end, which is exactly the error this is meant to remove.
        times = [float(value) for value in downbeats]
        if len(times) < n_measures:
            # Align from the END: an extra bar at the start (pickup, or a tracker
            # downbeat on the first sample) would otherwise shift every bar by one.
            step = times[1] - times[0] if len(times) > 1 else 2.0
            lead = n_measures - len(times)
            times = [times[0] - step * (lead - index) for index in range(lead)] + times
        return [(m, times[m - 1]) for m in range(1, n_measures + 1)]
    last = len(downbeats) - 1
    span = max(1, n_measures - 1)
    return [(m, float(downbeats[round((m - 1) * last / span)])) for m in range(1, n_measures + 1)]


def build_timemap(
    musicxml: bytes,
    alignment: dict[str, tuple[float, float]],
    grid: BeatGrid | None = None,
) -> dict:
    """Note times plus the barline time of every measure.

    The barline of a measure is not the first note: a measure can begin with a
    rest. Aligned notes give (score beat, performance seconds); the time of the
    barline follows by stepping back from the first aligned note by its beat
    offset inside the measure, at the local tempo (D-034).
    """
    notes = parse_score_notes(musicxml)
    measures: dict[int, float] = {}
    total = 0
    pairs: list[tuple[float, float]] = []
    for note in notes:
        total = max(total, note.measure)
        onset = alignment.get(note.note_id)
        if onset is None:
            continue
        pairs.append((note.beat, onset[0]))
    pairs.sort()
    for note in notes:
        total = max(total, note.measure)
        onset = alignment.get(note.note_id)
        if onset is None:
            continue
        slope = _local_slope(pairs, note.beat)
        barline = onset[0] - (note.beat - note.measure_start) * slope
        current = measures.get(note.measure)
        measures[note.measure] = barline if current is None else min(current, barline)
    snapped = _downbeat_onsets(grid.downbeats, total) if grid is not None and grid.downbeats else None
    if snapped is not None:
        measures = dict(snapped)
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
