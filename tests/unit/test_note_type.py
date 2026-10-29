"""Every written type plus its dots must add up to the duration (D-053)."""

from __future__ import annotations

from p2s.render.score_writer import NOTE_BASES, _note_type

DIVISIONS = 16


def _ticks(name: str, dots: int) -> float:
    base = next(value for value, candidate in NOTE_BASES if candidate == name)
    return base * DIVISIONS * (1 + (0.5 if dots >= 1 else 0) + (0.25 if dots >= 2 else 0))


def test_common_durations_round_trip() -> None:
    for duration in (64, 32, 16, 8, 4, 2, 24, 12, 6, 3, 1):
        name, dots = _note_type(duration, DIVISIONS)
        assert abs(_ticks(name, dots) - duration) <= 0.5, (duration, name, dots)


def test_dotted_values_are_named_after_their_base() -> None:
    assert _note_type(24, DIVISIONS) == ("quarter", 1)
    assert _note_type(12, DIVISIONS) == ("eighth", 1)
    assert _note_type(6, DIVISIONS) == ("16th", 1)
