"""Beaming units: simple metres per beat, compound metres in threes (D-051)."""

from __future__ import annotations

from p2s.render.score_writer import _beam_group_ticks


def test_simple_metre_groups_per_beat() -> None:
    assert _beam_group_ticks(3, 4, 16) == 16
    assert _beam_group_ticks(2, 4, 16) == 16
    assert _beam_group_ticks(4, 4, 16) == 16


def test_compound_metre_groups_three_eighths() -> None:
    # 6/8 at 16 divisions per quarter: one eighth is 8 ticks.
    assert _beam_group_ticks(6, 8, 8) == 24
    assert _beam_group_ticks(9, 8, 8) == 24
    assert _beam_group_ticks(12, 8, 8) == 24


def test_three_eight_beams_the_whole_bar() -> None:
    # A 3/8 bar is conventionally beamed as one group of three eighths.
    assert _beam_group_ticks(3, 8, 8) == 24
