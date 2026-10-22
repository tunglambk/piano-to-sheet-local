"""Timemap: score ids → original-file seconds (S7 output, FR-06)."""

from __future__ import annotations

import json
from pathlib import Path

from p2s.post.align import parse_score_notes


def build_timemap(musicxml: bytes, alignment: dict[str, tuple[float, float]]) -> dict:
    notes = parse_score_notes(musicxml)
    measures: dict[int, float] = {}
    for note in notes:
        onset = alignment.get(note.note_id)
        if onset is None:
            continue
        current = measures.get(note.measure)
        measures[note.measure] = onset[0] if current is None else min(current, onset[0])
    ordered_measures = sorted(measures.items())
    filled: list[dict] = []
    previous = 0.0
    for number, onset in ordered_measures:
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
