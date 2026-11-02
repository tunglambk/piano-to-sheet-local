"""The engraved score carries a work title and a composer (D-093)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.core.schemas import ScoreDoc
from p2s.post.s6 import postprocess

MINIMAL = b"""<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1"><attributes><divisions>16</divisions></attributes>
  <note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration>
  <type>quarter</type><staff>1</staff></note></measure></part>
</score-partwise>
"""


def _doc() -> ScoreDoc:
    return ScoreDoc(musicxml=MINIMAL, alignment={}, key=None, warnings=[])


def test_title_and_composer_are_written() -> None:
    root = ET.fromstring(postprocess(_doc(), title="La Campanella", composer="Franz Liszt").musicxml)
    assert root.findtext("work/work-title") == "La Campanella"
    assert root.findtext("movement-title") == "La Campanella"
    assert root.findtext("identification/creator") == "Franz Liszt"
    # MusicXML order: work and movement-title come before part-list.
    tags = [child.tag for child in root]
    assert tags.index("work") < tags.index("part-list")


def test_no_metadata_keeps_the_document_unchanged() -> None:
    root = ET.fromstring(postprocess(_doc()).musicxml)
    assert root.find("work") is None
    assert root.find("identification/creator") is None
