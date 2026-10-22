"""S7 alignment: coverage, monotonicity and range."""

from __future__ import annotations

from p2s.core.config import load_config
from p2s.core.schemas import BeatGrid, EngineInfo, NoteEvent, Performance, ScoreOptions
from p2s.engines.rulequant import RuleQuantizer
from p2s.post.align import align, parse_score_notes


def _engine() -> EngineInfo:
    return EngineInfo(id="perf", version="1", code_license="MIT", weight_license="MIT")


def _performance() -> Performance:
    notes = []
    for bar in range(2):
        for i, pitch in enumerate([60, 64, 67, 72]):
            onset = bar * 2.0 + i * 0.5 + 0.004
            notes.append(NoteEvent(pitch=pitch, onset=onset, offset=onset + 0.45, velocity=80))
    return Performance(notes=notes, engine=_engine())


def _grid() -> BeatGrid:
    beats = [i * 0.5 for i in range(10)]
    return BeatGrid(
        beats=beats,
        downbeats=[0.0, 2.0, 4.0],
        time_signatures=[(0.0, "4/4")],
        tempo_bpm=[(0.0, 120.0)],
        engine=_engine(),
    )


def test_alignment_covers_every_score_note() -> None:
    config = load_config()
    quantizer = RuleQuantizer(config.engines.get("score", "rule_quant"), config.lock.by_id("rule_quant"))
    score = quantizer.build(_performance(), _grid(), ScoreOptions())
    alignment, warnings = align(_performance(), score.musicxml, _grid())
    score_notes = parse_score_notes(score.musicxml)
    assert score_notes
    assert set(alignment) == {n.note_id for n in score_notes}
    assert not any("interpolated" in w for w in warnings)
    ordered = sorted(alignment.items(), key=lambda kv: kv[1][0])
    assert all(a[1][0] <= b[1][0] + 1e-6 for a, b in zip(ordered, ordered[1:], strict=False))


def test_alignment_stays_inside_the_performance() -> None:
    config = load_config()
    quantizer = RuleQuantizer(config.engines.get("score", "rule_quant"), config.lock.by_id("rule_quant"))
    perf = _performance()
    score = quantizer.build(perf, _grid(), ScoreOptions())
    alignment, _ = align(perf, score.musicxml, _grid())
    low = min(n.onset for n in perf.notes)
    high = max(n.offset for n in perf.notes)
    for onset, offset in alignment.values():
        assert low - 0.05 <= onset <= high + 0.05
        assert onset <= offset


def test_alignment_is_deterministic() -> None:
    config = load_config()
    quantizer = RuleQuantizer(config.engines.get("score", "rule_quant"), config.lock.by_id("rule_quant"))
    perf = _performance()
    score = quantizer.build(perf, _grid(), ScoreOptions())
    first, _ = align(perf, score.musicxml, _grid())
    second, _ = align(perf, score.musicxml, _grid())
    assert first == second
