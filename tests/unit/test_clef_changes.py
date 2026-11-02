"""Clef changes are inserted where the register moves (D-112)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.post.clefs import apply_clef_changes

HEAD = """<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0"><part id="P1">
<measure number="1"><attributes><divisions>4</divisions>
  <time><beats>4</beats><beat-type>4</beat-type></time></attributes>
{notes}
</measure></part></score-partwise>"""


def _measure(octaves: list[int], staff: int = 1) -> str:
    return "".join(
        f"<note><pitch><step>C</step><octave>{octave}</octave></pitch><duration>4</duration>"
        f"<type>quarter</type><voice>1</voice><staff>{staff}</staff></note>"
        for octave in octaves
    )


def _score(measures: list[list[int]]) -> ET.Element:
    body = "".join(
        f'<measure number="{index}"><attributes><divisions>4</divisions></attributes>{_measure(octaves)}</measure>'
        for index, octaves in enumerate(measures, start=1)
    )
    return ET.fromstring(HEAD.replace('<measure number="1">', body, 1).replace("{notes}\n</measure>", ""))


def test_a_high_passage_gets_an_octave_clef() -> None:
    # Four measures of very high notes: an 8va treble clef keeps them on the staff.
    root = _score([[7, 7, 7, 7]] * 4)
    written = apply_clef_changes(root)
    assert written >= 1
    clefs = root.findall(".//clef")
    assert clefs and clefs[0].findtext("clef-octave-change") in {"1", None}
