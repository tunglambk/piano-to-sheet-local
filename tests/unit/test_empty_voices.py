"""Voices that contain only rests are removed (D-107)."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.post.s6 import _drop_empty_voices

MEASURE = b"""<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0"><part id="P1"><measure number="1">
  <note><pitch><step>C</step><octave>4</octave></pitch><duration>16</duration><voice>1</voice><staff>1</staff></note>
  <backup><duration>16</duration></backup>
  <note><rest /><duration>16</duration><voice>2</voice><staff>1</staff></note>
</measure></part></score-partwise>
"""


def test_rest_only_voice_is_removed() -> None:
    root = ET.fromstring(MEASURE)
    dropped = _drop_empty_voices(root)
    assert dropped == 1
    voices = {note.findtext("voice") for note in root.iter("note")}
    assert voices == {"1"}


def test_a_voice_with_a_note_is_kept() -> None:
    root = ET.fromstring(MEASURE)
    root.find("part/measure").findall("note")[1].remove(
        root.find("part/measure").findall("note")[1].find("rest")
    )
    pitch = ET.SubElement(root.find("part/measure").findall("note")[1], "pitch")
    ET.SubElement(pitch, "step").text = "E"
    ET.SubElement(pitch, "octave").text = "4"
    assert _drop_empty_voices(root) == 0
