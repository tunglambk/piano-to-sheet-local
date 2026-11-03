"""Bar lines can be taken from the score model's own measures (D-118)."""

from __future__ import annotations

from p2s.post.align import ScoreNote
from p2s.post.rebar import _bar_times_from_score


def _note(note_id: str, measure: int) -> ScoreNote:
    return ScoreNote(note_id=note_id, pitch=60, staff=1, measure=measure, beat=0.0, duration_beats=1.0)


def test_one_time_per_measure_in_order() -> None:
    notes = [_note(f"n{m}", m) for m in range(1, 6)]
    alignment = {f"n{m}": (m * 2.0, m * 2.0 + 1.0) for m in range(1, 6)}
    times = _bar_times_from_score(notes, alignment)
    assert times == [2.0, 4.0, 6.0, 8.0, 10.0]


def test_a_misaligned_note_does_not_break_the_sequence() -> None:
    notes = [_note(f"n{m}", m) for m in range(1, 5)]
    alignment = {"n1": (1.0, 2.0), "n2": (5.0, 6.0), "n3": (3.0, 4.0), "n4": (7.0, 8.0)}
    times = _bar_times_from_score(notes, alignment)
    assert times is not None
    assert all(b > a for a, b in zip(times, times[1:], strict=False))


def test_too_few_measures_returns_none() -> None:
    notes = [_note("n1", 1), _note("n2", 2)]
    assert _bar_times_from_score(notes, {"n1": (0.0, 1.0), "n2": (2.0, 3.0)}) is None
