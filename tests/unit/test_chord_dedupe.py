"""A chord never repeats a pitch (D-102)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.render.score_writer import WriterNote, write_score


def test_repeated_pitch_inside_a_chord_is_dropped() -> None:
    notes = [
        WriterNote(pitch=60, start_tick=0, end_tick=16, staff=1, note_id="a"),
        WriterNote(pitch=60, start_tick=0, end_tick=16, staff=1, note_id="b"),
        WriterNote(pitch=64, start_tick=0, end_tick=16, staff=1, note_id="c"),
    ]
    root = ET.fromstring(
        write_score(notes, divisions=16, meters=[(4, 4)], fifths=0, mode="major", n_measures=1)
    )
    pitched = [n for n in root.findall(".//note") if n.find("pitch") is not None]
    assert len(pitched) == 2
    assert len(root.findall(".//chord")) == 1
