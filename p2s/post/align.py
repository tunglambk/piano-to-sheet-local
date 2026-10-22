"""S7 — score note ↔ performance time alignment (docs/design/s7-alignment.md).

S5 (M2ST) emits score positions, not performance seconds, and its output note
count differs from the input note count. So we align onset clusters with a
banded DTW over pitch sets, then map notes inside matched clusters by pitch.
Unmatched score notes are interpolated between their neighbours and marked in
`warnings`.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

from p2s.core.schemas import BeatGrid, Performance

SUBSTITUTION_WEIGHT = 1.0
INSERT_DELETE = 0.6
ONSET_TOLERANCE_S = 0.05


@dataclass
class ScoreNote:
    note_id: str
    pitch: int
    staff: int
    measure: int
    beat: float
    duration_beats: float
    step: str | None = None
    alter: int = 0
    octave: int | None = None


def _to_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _spelling_of(note: ET.Element) -> tuple[int, str, int, int] | None:
    pitch = note.find("pitch")
    if pitch is None:
        return None
    step = (pitch.findtext("step") or "C").upper()
    alter = _to_int(pitch.findtext("alter"), 0)
    octave = _to_int(pitch.findtext("octave"), 4)
    semitones = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step]
    return (octave + 1) * 12 + semitones + alter, step, alter, octave


def parse_score_notes(musicxml: bytes) -> list[ScoreNote]:
    root = ET.fromstring(musicxml)
    part = root.find("part")
    if part is None:
        return []
    attributes = part.find("measure/attributes")
    divisions = _to_int(attributes.findtext("divisions") if attributes is not None else None, 16)
    beats_per_bar = 4
    if attributes is not None and attributes.find("time") is not None:
        time_el = attributes.find("time")
        if time_el is not None:
            beats_per_bar = _to_int(time_el.findtext("beats"), 4)
    notes: list[ScoreNote] = []
    measure_start_beat = 0.0
    for measure_index, measure in enumerate(part.findall("measure"), start=1):
        position = 0
        staff = 1
        index_by_staff: dict[int, int] = {}
        measure_attrs = measure.find("attributes")
        if measure_attrs is not None and measure_attrs.find("time") is not None:
            time_el = measure_attrs.find("time")
            if time_el is not None:
                beats_per_bar = _to_int(time_el.findtext("beats"), beats_per_bar)
        for child in measure:
            if child.tag == "backup":
                position -= _to_int(child.findtext("duration"))
            elif child.tag == "forward":
                position += _to_int(child.findtext("duration"))
            elif child.tag == "note":
                staff = _to_int(child.findtext("staff"), staff)
                duration = _to_int(child.findtext("duration"))
                spelling = _spelling_of(child)
                if spelling is not None:
                    pitch, step, alter, octave = spelling
                    idx = index_by_staff.get(staff, 0)
                    index_by_staff[staff] = idx + 1
                    note_id = child.get("id") or f"n{staff}-{measure_index}-{idx}"
                    beat = measure_start_beat + position / divisions
                    notes.append(ScoreNote(note_id, pitch, staff, measure_index, beat, duration / divisions))
                if child.find("chord") is None:
                    position += duration
        measure_start_beat += beats_per_bar
    return notes


def _perf_clusters(perf: Performance) -> list[tuple[float, float, set[int], list[int]]]:
    clusters: list[list] = []
    for note in sorted(perf.notes, key=lambda n: (n.onset, n.pitch)):
        if clusters and note.onset - clusters[-1][0] <= ONSET_TOLERANCE_S:
            clusters[-1][1] = max(clusters[-1][1], note.offset)
            clusters[-1][2].add(note.pitch)
            clusters[-1][3].append(note.pitch)
        else:
            clusters.append([note.onset, note.offset, {note.pitch}, [note.pitch]])
    return [(float(c[0]), float(c[1]), set(c[2]), list(c[3])) for c in clusters]


def _score_clusters(notes: list[ScoreNote]) -> list[tuple[float, float, set[int], list[ScoreNote]]]:
    clusters: list[list] = []
    for note in sorted(notes, key=lambda n: (n.beat, n.pitch)):
        if clusters and abs(note.beat - clusters[-1][0]) < 1e-6:
            clusters[-1][1] = max(clusters[-1][1], note.beat + note.duration_beats)
            clusters[-1][2].add(note.pitch)
            clusters[-1][3].append(note)
        else:
            clusters.append([note.beat, note.beat + note.duration_beats, {note.pitch}, [note]])
    return [(float(c[0]), float(c[1]), set(c[2]), list(c[3])) for c in clusters]


def _cost(a: set[int], b: set[int]) -> float:
    union = a | b
    if not union:
        return 0.0
    return SUBSTITUTION_WEIGHT * (1.0 - len(a & b) / len(union))


def align(
    perf: Performance, musicxml: bytes, grid: BeatGrid | None = None
) -> tuple[dict[str, tuple[float, float]], list[str]]:
    warnings: list[str] = []
    score_notes = parse_score_notes(musicxml)
    if not score_notes:
        return {}, ["alignment: the score has no notes"]
    if not perf.notes:
        return {}, ["alignment: the performance has no notes"]
    perf_clusters = _perf_clusters(perf)
    score_clusters = _score_clusters(score_notes)
    n, m = len(perf_clusters), len(score_clusters)
    band = max(20, int(abs(n - m)) + 40)
    inf = float("inf")
    dp = [[inf] * (m + 1) for _ in range(n + 1)]
    step: list[list[tuple[int, int] | None]] = [[None] * (m + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for i in range(n + 1):
        centre = int(i * m / max(1, n))
        for j in range(max(0, centre - band), min(m, centre + band) + 1):
            if i == 0 and j == 0:
                continue
            best_value: float = inf
            best_step: tuple[int, int] | None = None
            if i > 0 and j > 0:
                value = dp[i - 1][j - 1] + _cost(perf_clusters[i - 1][2], score_clusters[j - 1][2])
                if value < best_value:
                    best_value, best_step = value, (i - 1, j - 1)
            if i > 0:
                value = dp[i - 1][j] + INSERT_DELETE
                if value < best_value:
                    best_value, best_step = value, (i - 1, j)
            if j > 0:
                value = dp[i][j - 1] + INSERT_DELETE
                if value < best_value:
                    best_value, best_step = value, (i, j - 1)
            dp[i][j] = best_value
            step[i][j] = best_step
    if dp[n][m] == inf:
        warnings.append("alignment: DTW found no path; falling back to beat positions")
        return _beat_fallback(score_notes, perf, grid, warnings)
    pairs: list[tuple[int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        pairs.append((i - 1, j - 1))
        previous = step[i][j]
        if previous is None:
            break
        i, j = previous
    pairs.reverse()
    mapping: dict[str, tuple[float, float]] = {}
    matched = 0
    for i, j in pairs:
        if i < 0 or j < 0:
            continue
        onset, offset, _pitches, pnotes = perf_clusters[i]
        _sbeat, _seb, _spitches, snodes = score_clusters[j]
        by_pitch: dict[int, tuple[float, float]] = {}
        for pitch in pnotes:
            by_pitch.setdefault(pitch, (onset, offset))
        for note in snodes:
            times = by_pitch.get(note.pitch)
            if times is None:
                times = (onset, offset)
            mapping[note.note_id] = times
            matched += 1
    missing = [n.note_id for n in score_notes if n.note_id not in mapping]
    if missing:
        warnings.append(f"alignment: {len(missing)} score notes interpolated")
        ordered = [n for n in score_notes if n.note_id in mapping]
        known = sorted((n.beat, mapping[n.note_id][0]) for n in ordered)
        for note in score_notes:
            if note.note_id in mapping:
                continue
            near = min(known, key=lambda kb: abs(kb[0] - note.beat)) if known else (note.beat, 0.0)
            duration = max(0.05, note.duration_beats * 0.5)
            mapping[note.note_id] = (near[1], near[1] + duration)
    result = {k: (round(v[0], 6), round(v[1], 6)) for k, v in mapping.items()}
    if result:
        ordered = sorted(result.items(), key=lambda kv: kv[1][0])
        monotonic = all(a[1][0] <= b[1][0] + 1e-6 for a, b in zip(ordered, ordered[1:], strict=False))
        if not monotonic:
            warnings.append("alignment: times are not monotonic")
    return result, warnings


def _beat_fallback(
    score_notes: list[ScoreNote], perf: Performance, grid: BeatGrid | None, warnings: list[str]
) -> tuple[dict[str, tuple[float, float]], list[str]]:
    if grid is None or len(grid.beats) < 2:
        return {}, warnings + ["alignment: no fallback grid"]
    beats = grid.beats

    def beat_to_s(beat: float) -> float:
        if beat <= 0:
            return beats[0]
        idx = int(beat)
        if idx + 1 < len(beats):
            frac = beat - idx
            return beats[idx] + frac * (beats[idx + 1] - beats[idx])
        span = beats[-1] - beats[-2]
        return beats[-1] + (beat - len(beats) + 1) * span

    return {
        n.note_id: (beat_to_s(n.beat), beat_to_s(n.beat + n.duration_beats)) for n in score_notes
    }, warnings
