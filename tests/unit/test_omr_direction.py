"""OMR-NED is a distance: identical scores score 0, worse scores score higher.

The direction was read backwards for most of this project (D-115). This test pins it
using synthetic MusicXML, so it fails loudly if the metric is ever wired the other
way round.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bench.metrics.l3_omrned import available, omr_ned

SCORE = b"""<?xml version="1.0" encoding="utf-8"?>
<score-partwise version="4.0">
  <part-list><score-part id="P1"><part-name>Piano</part-name></score-part></part-list>
  <part id="P1"><measure number="1">
    <attributes><divisions>4</divisions>
      <key><fifths>0</fifths></key>
      <time><beats>4</beats><beat-type>4</beat-type></time>
      <clef number="1"><sign>G</sign><line>2</line></clef>
    </attributes>
    <note><pitch><step>C</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type><voice>1</voice><staff>1</staff></note>
    <note><pitch><step>D</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type><voice>1</voice><staff>1</staff></note>
    <note><pitch><step>E</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type><voice>1</voice><staff>1</staff></note>
    <note><pitch><step>F</step><octave>4</octave></pitch><duration>4</duration><type>quarter</type><voice>1</voice><staff>1</staff></note>
  </measure></part>
</score-partwise>
"""


@pytest.mark.skipif(not available(), reason="VeroSim is not built in this checkout")
def test_identical_scores_score_zero(tmp_path: Path) -> None:
    reference = tmp_path / "ref.musicxml"
    reference.write_bytes(SCORE)
    copy = tmp_path / "copy.musicxml"
    shutil.copyfile(reference, copy)
    value = omr_ned(copy, reference)
    assert value is not None and value == 0.0


@pytest.mark.skipif(not available(), reason="VeroSim is not built in this checkout")
def test_a_degraded_score_scores_higher(tmp_path: Path) -> None:
    reference = tmp_path / "ref.musicxml"
    reference.write_bytes(SCORE)
    degraded = tmp_path / "degraded.musicxml"
    degraded.write_bytes(
        SCORE.replace(b"<step>D</step>", b"<step>G</step>").replace(b"<step>E</step>", b"<step>B</step>")
    )
    value = omr_ned(degraded, reference)
    assert value is not None and value > 0.0
