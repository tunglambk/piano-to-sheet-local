"""Chord handling is deliberately switched off until the writer can emit safe markup.

The onset clustering that would feed `<chord/>` is in place (D-096) and the emission
is disabled because VeroSim and Verovio segfault on our chord output (D-097). These
tests pin the *current* contract: no `<chord/>`, and a bar whose notes share an onset
still fills exactly one bar.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.render.score_writer import WriterNote, write_score


def _score(notes: list[WriterNote]) -> ET.Element:
    return ET.fromstring(
        write_score(notes, divisions=16, meters=[(4, 4)], fifths=0, mode="major", n_measures=1)
    )


def test_chords_are_not_emitted_while_disabled() -> None:
    notes = [
        WriterNote(pitch=60, start_tick=0, end_tick=16, staff=1, note_id="a"),
        WriterNote(pitch=64, start_tick=0, end_tick=16, staff=1, note_id="b"),
    ]
    root = _score(notes)
    assert root.findall(".//chord") == []
    assert len([n for n in root.findall(".//note") if n.find("pitch") is not None]) == 2


def test_a_bar_with_simultaneous_notes_is_still_one_bar() -> None:
    notes = [
        WriterNote(pitch=60, start_tick=0, end_tick=16, staff=1, note_id="a"),
        WriterNote(pitch=64, start_tick=0, end_tick=16, staff=1, note_id="b"),
    ]
    measure = _score(notes).find(".//measure")
    total = sum(int(n.findtext("duration") or 0) for n in measure.findall("note"))
    assert total >= 64  # the writer never leaves the bar short
