"""Rebuild the score's bar structure from the tracked downbeats (D-038).

M2ST keeps its own tempo and metre, so its bar lines drift from what was played
(measured: up to 3.2 beats on the P2S-Open dev split). The notes and their
spelling are good; only the bar grid is wrong. This module re-cuts the notes at
the performance's downbeats: every note keeps its pitch, staff and spelling, and
its onset is placed proportionally inside the bar that contains it.
"""

from __future__ import annotations

from bisect import bisect_right
from xml.etree import ElementTree as ET

from p2s.core.schemas import BeatGrid
from p2s.post.align import parse_score_notes
from p2s.render.score_writer import WriterNote, write_score

DIVISIONS = 16
DEFAULT_BEATS_PER_BAR = 4
MIN_COVERAGE = 0.6


def _source_key(musicxml: bytes) -> tuple[int, str]:
    """Key signature the score model chose (D-052).

    Estimating the key from the performance produced absurd signatures (D-049), but
    the source score already carries one — the score model emits `<key><fifths>`
    (for example -3 for a piece in E flat major). Re-engraving must not throw it
    away.
    """
    part = ET.fromstring(musicxml).find("part")
    key_el = part.find("measure/attributes/key") if part is not None else None
    if key_el is None:
        return 0, "major"
    try:
        fifths = int(key_el.findtext("fifths") or 0)
    except ValueError:
        fifths = 0
    mode = (key_el.findtext("mode") or "major").strip() or "major"
    return max(-7, min(7, fifths)), mode


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


def _beats_per_bar(beats: list[float], downbeats: list[float]) -> int:
    """Beats between consecutive downbeats, as the tracker hears them."""
    counts: dict[int, int] = {}
    for previous, current in zip(downbeats, downbeats[1:], strict=False):
        value = sum(1 for beat in beats if previous - 1e-6 <= beat < current - 1e-6)
        if 2 <= value <= 12:
            counts[value] = counts.get(value, 0) + 1
    if not counts:
        return DEFAULT_BEATS_PER_BAR
    return max(counts.items(), key=lambda item: item[1])[0]


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

    source_fifths, source_mode = _source_key(musicxml)

    # The metre comes from the tracker, not from a constant: engraving everything
    # in 4/4 left a third of the bars empty on a 3/4 piece (D-048).
    beats_per_bar = _beats_per_bar(grid.beats, grid.downbeats)
    bar_ticks = DIVISIONS * beats_per_bar

    writer_notes: list[WriterNote] = []
    for note, value in aligned:
        if value is None:
            continue
        onset, offset = value
        index = max(0, min(len(bars) - 1, bisect_right(bars, onset) - 1))
        bar_start = bars[index]
        bar_end = bars[index + 1] if index + 1 < len(bars) else bar_start + (bars[-1] - bars[-2])
        width = max(1e-3, bar_end - bar_start)
        start = int(round((onset - bar_start) / width * bar_ticks))
        end = int(round((offset - bar_start) / width * bar_ticks))
        start = max(0, min(bar_ticks - 1, start))
        end = max(start + 1, min(bar_ticks, end))
        writer_notes.append(
            WriterNote(
                pitch=note.pitch,
                start_tick=index * bar_ticks + start,
                end_tick=index * bar_ticks + end,
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
        meters=[(beats_per_bar, 4)] * len(bars),
        fifths=source_fifths,
        mode=source_mode,
        n_measures=len(bars),
    )
