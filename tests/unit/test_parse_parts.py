"""Every part of a score is read, not just the first (D-100)."""

from __future__ import annotations

from p2s.post.align import parse_score_notes

TWO_PARTS = b"""<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0">
  <part-list>
    <score-part id="P1"><part-name>Right</part-name></score-part>
    <score-part id="P2"><part-name>Left</part-name></score-part>
  </part-list>
  <part id="P1"><measure number="1"><attributes><divisions>4</divisions>
    <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>5</octave></pitch><duration>4</duration><type>quarter</type></note>
  </measure></part>
  <part id="P2"><measure number="1"><attributes><divisions>4</divisions>
    <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
    <note><pitch><step>C</step><octave>3</octave></pitch><duration>4</duration><type>quarter</type></note>
  </measure></part>
</score-partwise>
"""


def test_both_parts_are_parsed() -> None:
    notes = parse_score_notes(TWO_PARTS)
    assert len(notes) == 2
    assert {note.staff for note in notes} == {1, 2}
    assert {note.pitch for note in notes} == {48, 72}


def test_part_index_becomes_the_staff() -> None:
    notes = parse_score_notes(TWO_PARTS)
    by_staff = {note.staff: note.pitch for note in notes}
    assert by_staff[1] == 72  # part 0, right hand
    assert by_staff[2] == 48  # part 1, left hand
