"""Notes that share an onset are engraved as one chord (D-098).

The markup must stay importable: VeroSim and Verovio segfaulted on chord members
with a different duration and on a chord with no note before it (D-097).
"""

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


def test_chord_members_share_the_anchor_duration() -> None:
    notes = [
        WriterNote(pitch=60, start_tick=0, end_tick=8, staff=1, note_id="a"),
        WriterNote(pitch=64, start_tick=0, end_tick=32, staff=1, note_id="b"),
    ]
    root = _score(notes)
    durations = {n.findtext("duration") for n in root.findall(".//note") if n.find("pitch") is not None}
    assert len(durations) == 1, durations


def test_no_chord_without_a_note_before_it() -> None:
    notes = [
        WriterNote(pitch=60, start_tick=0, end_tick=16, staff=1, note_id="a"),
        WriterNote(pitch=64, start_tick=16, end_tick=32, staff=1, note_id="b"),
    ]
    root = _score(notes)
    for measure in root.findall(".//measure"):
        previous = None
        for element in measure:
            if element.tag != "note":
                previous = None
                continue
            if element.find("chord") is not None:
                assert previous is not None and previous.find("pitch") is not None
            previous = element
