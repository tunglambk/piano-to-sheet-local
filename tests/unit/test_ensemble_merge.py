"""Ensemble vote policies on tiny synthetic performances."""

from __future__ import annotations

from p2s.core.schemas import EngineInfo, NoteEvent, Performance
from p2s.post.ensemble import merge

ENGINE = EngineInfo(
    id="t",
    version="0",
    weights_sha256={},
    code_license="MIT",
    weight_license="MIT",
    commercial_use="yes",
    device="cpu",
    kind="inprocess",
)


def perf(notes: list[tuple[float, int, int]]) -> Performance:
    return Performance(
        notes=[NoteEvent(onset=o, offset=o + 0.5, pitch=p, velocity=v) for o, p, v in notes], engine=ENGINE
    )


def test_agreement_is_kept() -> None:
    a = perf([(1.0, 60, 90), (2.0, 64, 90)])
    b = perf([(1.01, 60, 90)])
    merged = merge([a, b])
    assert [n.pitch for n in merged.notes] == [60]


def test_high_velocity_extra_survives() -> None:
    a = perf([(1.0, 60, 90)])
    b = perf([(1.0, 60, 90), (3.0, 67, 120)])
    merged = merge([a, b])
    assert [n.pitch for n in merged.notes] == [60, 67]


def test_intersection_policy_drops_extras() -> None:
    a = perf([(1.0, 60, 90)])
    b = perf([(1.0, 60, 90), (3.0, 67, 120)])
    merged = merge([a, b], vote="intersection")
    assert [n.pitch for n in merged.notes] == [60]
