"""Notes that share an onset are engraved as one chord (D-096)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.render.score_writer import WriterNote, write_score


def _score(notes: list[WriterNote]) -> ET.Element:
    return ET.fromstring(
        write_score(notes, divisions=16, meters=[(4, 4)], fifths=0, mode="major", n_measures=1)
    )


def test_simultaneous_notes_become_a_chord() -> None:
    notes = [
        WriterNote(pitch=60, start_tick=0, end_tick=16, staff=1, note_id="a"),
        WriterNote(pitch=64, start_tick=0, end_tick=16, staff=1, note_id="b"),
        WriterNote(pitch=67, start_tick=0, end_tick=16, staff=1, note_id="c"),
    ]
    root = _score(notes)
    assert len(root.findall(".//chord")) == 2
    assert len([n for n in root.findall(".//note") if n.find("pitch") is not None]) == 3


def test_sequential_notes_have_no_chord() -> None:
    notes = [
        WriterNote(pitch=60, start_tick=0, end_tick=16, staff=1, note_id="a"),
        WriterNote(pitch=62, start_tick=16, end_tick=32, staff=1, note_id="b"),
    ]
    assert _score(notes).findall(".//chord") == []


def test_a_chord_does_not_advance_the_bar() -> None:
    notes = [
        WriterNote(pitch=60, start_tick=0, end_tick=16, staff=1, note_id="a"),
        WriterNote(pitch=64, start_tick=0, end_tick=16, staff=1, note_id="b"),
    ]
    rests = [n for n in _score(notes).findall(".//note") if n.find("rest") is not None]
    assert rests and rests[0].findtext("duration") == "48"
