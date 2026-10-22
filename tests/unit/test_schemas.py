"""Schema contract tests (spec §5.2, D-023)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from p2s.core.schemas import (
    BeatGrid,
    EngineInfo,
    NoteEvent,
    Performance,
    ScoreDoc,
)


def engine() -> EngineInfo:
    return EngineInfo(id="test", version="1", code_license="MIT", weight_license="MIT")


def test_note_ranges_are_enforced() -> None:
    with pytest.raises(ValidationError):
        NoteEvent(pitch=20, onset=0.0, offset=1.0, velocity=80)
    with pytest.raises(ValidationError):
        NoteEvent(pitch=109, onset=0.0, offset=1.0, velocity=80)
    with pytest.raises(ValidationError):
        NoteEvent(pitch=60, onset=0.0, offset=1.0, velocity=0)
    with pytest.raises(ValidationError):
        NoteEvent(pitch=60, onset=1.0, offset=0.5, velocity=80)


def test_performance_round_trip() -> None:
    perf = Performance(
        notes=[NoteEvent(pitch=60, onset=0.1, offset=0.6, velocity=90)], pedals=[(0.0, 1.0)], engine=engine()
    )
    again = Performance.model_validate_json(perf.model_dump_json())
    assert again == perf


def test_score_doc_transports_bytes_as_base64() -> None:
    doc = ScoreDoc(musicxml=b"<score-partwise/>", alignment={"n1-1-0": (0.1, 0.5)})
    payload = json.loads(doc.model_dump_json())
    assert payload["musicxml"] == "PHNjb3JlLXBhcnR3aXNlLz4="
    assert ScoreDoc.model_validate_json(doc.model_dump_json()) == doc


def test_beat_grid_offset_round_trip() -> None:
    grid = BeatGrid(
        beats=[0.5, 1.0],
        downbeats=[0.5],
        time_signatures=[(0.5, "4/4")],
        tempo_bpm=[(0.5, 120.0)],
        engine=engine(),
    )
    assert BeatGrid.model_validate_json(grid.model_dump_json()) == grid
