"""6/8 beams in groups of three eighths, end to end through the writer (D-073)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.render.score_writer import WriterNote, write_score

DIVISIONS = 16
EIGHTH = DIVISIONS // 2  # one eighth note in ticks


def _beams(xml: bytes) -> list[str]:
    root = ET.fromstring(xml)
    states: list[str] = []
    for note in root.findall(".//note"):
        beam = note.find("beam")
        if beam is None:
            continue
        states.append((beam.text or "").strip())
    return states


def test_six_eight_beams_two_groups_of_three() -> None:
    notes = [
        WriterNote(
            pitch=60 + index,
            start_tick=index * EIGHTH,
            end_tick=(index + 1) * EIGHTH,
            staff=1,
            note_id=f"n{index}",
        )
        for index in range(6)
    ]
    xml = write_score(notes, divisions=DIVISIONS, meters=[(6, 8)], fifths=0, mode="major", n_measures=1)
    assert _beams(xml) == ["begin", "continue", "end", "begin", "continue", "end"]


def test_three_four_beams_one_group_per_beat() -> None:
    notes = [
        WriterNote(
            pitch=60 + index,
            start_tick=index * EIGHTH,
            end_tick=(index + 1) * EIGHTH,
            staff=1,
            note_id=f"m{index}",
        )
        for index in range(6)
    ]
    xml = write_score(notes, divisions=DIVISIONS, meters=[(3, 4)], fifths=0, mode="major", n_measures=1)
    # 3/4 groups per beat: pairs [0,1] and [2,3] and [4,5].
    assert _beams(xml) == ["begin", "end", "begin", "end", "begin", "end"]


def test_six_eight_time_signature_is_written() -> None:
    note = WriterNote(pitch=60, start_tick=0, end_tick=4 * EIGHTH, staff=1, note_id="w")
    root = ET.fromstring(
        write_score([note], divisions=DIVISIONS, meters=[(6, 8)], fifths=0, mode="major", n_measures=1)
    )
    assert root.findtext(".//time/beats") == "6"
    assert root.findtext(".//time/beat-type") == "8"
