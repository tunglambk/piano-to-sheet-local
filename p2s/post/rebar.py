"""Rebuild the score's bar structure from the tracked downbeats (D-038).

M2ST keeps its own tempo and metre, so its bar lines drift from what was played
(measured: up to 3.2 beats on the P2S-Open dev split). The notes and their
spelling are good; only the bar grid is wrong. This module re-cuts the notes at
the performance's downbeats: every note keeps its pitch, staff and spelling, and
its onset is placed proportionally inside the bar that contains it.
"""

from __future__ import annotations

from bisect import bisect_right

from p2s.core.schemas import BeatGrid
from p2s.post.align import parse_score_notes
from p2s.render.score_writer import WriterNote, write_score

DIVISIONS = 16
BEATS_PER_BAR = 4
BAR_TICKS = DIVISIONS * BEATS_PER_BAR
MIN_COVERAGE = 0.6


def _bar_times(downbeats: list[float], beats: list[float], duration_s: float) -> list[float]:
    # A downbeat before the first tracked beat is an artefact of the start of the
    # audio, not a bar line: keeping it adds a bar and shifts every later one.
    floor = beats[0] - 1e-6 if beats else 0.0
    times = [value for value in downbeats if value >= floor]
    if len(times) < 4:
        return []
    typical = sorted(b - a for a, b in zip(times, times[1:], strict=False))
    step = typical[len(typical) // 2] if typical else 2.0
    # The tracker often misses the last downbeat when the recording fades out, but
    # it still marks the beats of that final bar: close the bar as soon as a beat
    # follows the last downbeat.
    continues = bool(beats) and beats[-1] > times[-1] + 1e-6
    if continues or duration_s > times[-1] + 0.5 * step:
        times = [*times, times[-1] + step]
    return times


def bar_count(grid: BeatGrid | None, duration_s: float) -> int:
    """How many bars this grid would produce (used to choose between grids)."""
    if grid is None:
        return 0
    return len(_bar_times(grid.downbeats, grid.beats, duration_s))


def rebar(
    musicxml: bytes,
    alignment: dict[str, tuple[float, float]],
    grid: BeatGrid | None,
    duration_s: float | None = None,
) -> bytes | None:
    """Return a re-barred MusicXML, or None when the grid cannot support one."""
    if grid is None or len(grid.downbeats) < 4 or not alignment:
        return None
    notes = parse_score_notes(musicxml)
    if not notes:
        return None
    aligned = [(note, alignment.get(note.note_id)) for note in notes]
    covered = sum(1 for _, value in aligned if value is not None)
    if covered < MIN_COVERAGE * len(notes):
        return None

    span = float(duration_s or (max(value[1] for _, value in aligned if value) + 0.5))
    bars = _bar_times(grid.downbeats, grid.beats, span)
    if len(bars) < 4:
        return None

    writer_notes: list[WriterNote] = []
    for note, value in aligned:
        if value is None:
            continue
        onset, offset = value
        index = max(0, min(len(bars) - 1, bisect_right(bars, onset) - 1))
        bar_start = bars[index]
        bar_end = bars[index + 1] if index + 1 < len(bars) else bar_start + (bars[-1] - bars[-2])
        width = max(1e-3, bar_end - bar_start)
        start = int(round((onset - bar_start) / width * BAR_TICKS))
        end = int(round((offset - bar_start) / width * BAR_TICKS))
        start = max(0, min(BAR_TICKS - 1, start))
        end = max(start + 1, min(BAR_TICKS, end))
        writer_notes.append(
            WriterNote(
                pitch=note.pitch,
                start_tick=index * BAR_TICKS + start,
                end_tick=index * BAR_TICKS + end,
                staff=note.staff,
                note_id=note.note_id,
                step=note.step,
                alter=note.alter,
                octave=note.octave,
            )
        )
    if not writer_notes:
        return None
    return write_score(
        writer_notes,
        divisions=DIVISIONS,
        meters=[(BEATS_PER_BAR, 4)] * len(bars),
        fifths=0,
        mode="major",
        n_measures=len(bars),
    )
