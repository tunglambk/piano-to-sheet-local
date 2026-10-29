"""A note that crosses a barline is written as two tied notes (D-060)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.render.score_writer import WriterNote, write_score

DIVISIONS = 16
BAR = DIVISIONS * 3  # 3/4


def _write(notes: list[WriterNote], measures: int) -> ET.Element:
    xml = write_score(
        notes, divisions=DIVISIONS, meters=[(3, 4)] * measures, fifths=0, mode="major", n_measures=measures
    )
    return ET.fromstring(xml)


def test_note_across_a_barline_is_tied() -> None:
    # Starts on beat 2 of bar 1 and sustains into bar 2.
    crossing = WriterNote(pitch=60, start_tick=20, end_tick=BAR + 20, staff=1, note_id="n-cross")
    root = _write([crossing], measures=2)
    notes = root.findall(".//note")
    assert len(notes) >= 2
    starts = [
        note for note in notes if note.find("tie") is not None and note.find("tie").get("type") == "start"
    ]
    stops = [
        note for note in notes if note.find("tie") is not None and note.find("tie").get("type") == "stop"
    ]
    assert starts and stops
    # Durations are rounded to writable values (D-054): 28 and 16 at 16 divisions.
    assert starts[0].findtext("duration") == str(28)
    assert stops[0].findtext("duration") == str(16)
    # The ids stay distinct so the viewer can highlight both halves.
    assert starts[0].get("id") != stops[0].get("id")


def test_note_inside_one_bar_has_no_tie() -> None:
    inside = WriterNote(pitch=62, start_tick=0, end_tick=16, staff=1, note_id="n-simple")
    root = _write([inside], measures=1)
    assert root.findall(".//tie") == []


def test_crossing_note_written_durations_are_representable() -> None:
    crossing = WriterNote(pitch=64, start_tick=8, end_tick=BAR + 24, staff=1, note_id="n-cross2")
    root = _write([crossing], measures=2)
    bases = {
        "whole": 4.0,
        "half": 2.0,
        "quarter": 1.0,
        "eighth": 0.5,
        "16th": 0.25,
        "32nd": 0.125,
        "64th": 0.0625,
    }
    for note in root.findall(".//note"):
        written = note.findtext("type")
        if written is None:
            continue
        dots = len(note.findall("dot"))
        expected = bases[written] * DIVISIONS * (1 + (0.5 if dots else 0) + (0.25 if dots >= 2 else 0))
        assert abs(expected - int(note.findtext("duration") or 0)) <= 0.6
