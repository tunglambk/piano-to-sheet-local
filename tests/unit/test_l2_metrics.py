"""L2 note metrics on a tiny known pair."""

from __future__ import annotations

from bench.metrics.l2_notes import evaluate
from p2s.core.schemas import EngineInfo, NoteEvent, Performance

ENGINE = EngineInfo(
    id="test",
    version="0",
    weights_sha256={},
    code_license="MIT",
    weight_license="MIT",
    commercial_use="yes",
    device="cpu",
    kind="inprocess",
)


def perf(notes: list[tuple[float, float, int]]) -> Performance:
    return Performance(
        notes=[NoteEvent(pitch=p, onset=o, offset=off, velocity=80) for o, off, p in notes],
        engine=ENGINE,
    )


def test_perfect_match_scores_one() -> None:
    reference = perf([(1.0, 2.0, 60), (2.0, 3.0, 64)])
    result = evaluate(reference, reference)
    assert result["onset_f1"] == 1.0
    assert result["note_f1"] == 1.0


def test_tolerance_and_wrong_pitch() -> None:
    reference = perf([(1.0, 2.0, 60), (2.0, 3.0, 64)])
    predicted = perf([(1.02, 2.0, 60), (2.0, 3.0, 65)])
    result = evaluate(predicted, reference)
    assert result["onset_f1"] == 0.5
    assert result["pitch_f1"] == 0.5


def test_empty_side_scores_zero() -> None:
    assert evaluate(perf([]), perf([(1.0, 2.0, 60)]))["onset_f1"] == 0.0
