"""Rule quantiser: determinism, structure, hands and ties."""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s.core.config import load_config
from p2s.core.schemas import BeatGrid, EngineInfo, NoteEvent, Performance, ScoreOptions
from p2s.engines.rulequant import RuleQuantizer


def _engine() -> EngineInfo:
    return EngineInfo(id="perf", version="1", code_license="MIT", weight_license="MIT")


def _grid(bpm: float = 120.0, bars: int = 4, beats_per_bar: int = 4) -> BeatGrid:
    beat = 60.0 / bpm
    beats = [i * beat for i in range(bars * beats_per_bar + 1)]
    downbeats = [i * beats_per_bar * beat for i in range(bars + 1)]
    return BeatGrid(
        beats=beats,
        downbeats=downbeats,
        time_signatures=[(0.0, f"{beats_per_bar}/4")],
        tempo_bpm=[(0.0, bpm)],
        engine=_engine(),
    )


def _quantizer() -> RuleQuantizer:
    config = load_config()
    return RuleQuantizer(config.engines.get("score", "rule_quant"), config.lock.by_id("rule_quant"))


def test_scale_is_quantized_exactly() -> None:
    notes = [
        NoteEvent(pitch=p, onset=i * 0.5 + 0.002, offset=i * 0.5 + 0.498, velocity=80)
        for i, p in enumerate([60, 62, 64, 65, 67, 69, 71, 72])
    ]
    doc = _quantizer().build(Performance(notes=notes, engine=_engine()), _grid(), ScoreOptions())
    root = ET.fromstring(doc.musicxml)
    measures = root.findall(".//measure")
    assert len(measures) == 2
    onsets = [
        (int(n.findtext("duration")), n.findtext("pitch/step"))
        for n in root.findall(".//note")
        if n.find("pitch") is not None
    ]
    assert onsets[0] == (16, "C")
    assert len(onsets) == 8


def test_hands_split_and_two_staves() -> None:
    notes = [
        NoteEvent(pitch=40, onset=0.0, offset=0.5, velocity=60),
        NoteEvent(pitch=76, onset=0.0, offset=0.5, velocity=90),
    ]
    doc = _quantizer().build(Performance(notes=notes, engine=_engine()), _grid(), ScoreOptions())
    root = ET.fromstring(doc.musicxml)
    staffs = {n.findtext("staff") for n in root.findall(".//note") if n.find("pitch") is not None}
    assert staffs == {"1", "2"}


def test_note_crossing_barline_becomes_tied() -> None:
    notes = [NoteEvent(pitch=60, onset=1.5, offset=2.5, velocity=80)]
    doc = _quantizer().build(Performance(notes=notes, engine=_engine()), _grid(), ScoreOptions())
    root = ET.fromstring(doc.musicxml)
    ties = [n.find("tie") for n in root.findall(".//note") if n.find("pitch") is not None]
    assert any(t is not None and t.get("type") == "start" for t in ties)
    assert any(t is not None and t.get("type") == "stop" for t in ties)


def test_output_is_deterministic() -> None:
    notes = [NoteEvent(pitch=60 + i, onset=i * 0.25, offset=i * 0.25 + 0.2, velocity=70) for i in range(16)]
    quantizer = _quantizer()
    a = quantizer.build(Performance(notes=notes, engine=_engine()), _grid(), ScoreOptions())
    b = quantizer.build(Performance(notes=notes, engine=_engine()), _grid(), ScoreOptions())
    assert a.musicxml == b.musicxml


def test_empty_performance_yields_rests() -> None:
    doc = _quantizer().build(Performance(notes=[], engine=_engine()), _grid(), ScoreOptions())
    root = ET.fromstring(doc.musicxml)
    assert root.findall(".//rest")
    assert doc.warnings
