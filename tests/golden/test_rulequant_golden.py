"""Golden MusicXML for the deterministic S5–S8 path (D-016).

The golden covers the rule quantiser plus the S6 normaliser, which are the parts
of the pipeline that must be byte-stable without a GPU. Upstream engines
(Transkun, Beat This!, M2ST) get version-pinned cache keys instead.
"""

from __future__ import annotations

from pathlib import Path

from p2s.core.config import load_config
from p2s.core.schemas import BeatGrid, EngineInfo, NoteEvent, Performance, ScoreOptions
from p2s.engines.rulequant import RuleQuantizer
from p2s.post.s6 import postprocess

GOLDEN = Path(__file__).parent / "data" / "rulequant_scale.musicxml"


def _fixture() -> tuple[Performance, BeatGrid]:
    info = EngineInfo(id="golden", version="1", code_license="MIT", weight_license="MIT")
    notes = []
    for i, (pitch, vel) in enumerate(
        zip([60, 62, 64, 65, 67, 69, 71, 72, 60, 64, 67, 72], [80] * 12, strict=False)
    ):
        onset = i * 0.25 + 0.004
        notes.append(NoteEvent(pitch=pitch, onset=onset, offset=onset + 0.2, velocity=vel))
    perf = Performance(notes=notes, engine=info)
    beats = [i * 0.25 for i in range(13)]
    grid = BeatGrid(
        beats=beats,
        downbeats=[0.0, 1.0, 2.0, 3.0],
        time_signatures=[(0.0, "4/4")],
        tempo_bpm=[(0.0, 240.0)],
        engine=info,
    )
    return perf, grid


def _render() -> bytes:
    config = load_config()
    quantizer = RuleQuantizer(config.engines.get("score", "rule_quant"), config.lock.by_id("rule_quant"))
    perf, grid = _fixture()
    score = quantizer.build(perf, grid, ScoreOptions(quantize_grid="1/16"))
    return postprocess(score).musicxml


def _stable(xml: bytes) -> bytes:
    """Version bumps must not fail the golden; a separate test checks the version."""
    import re

    return re.sub(rb"<software>p2s [0-9.]+</software>", b"<software>p2s</software>", xml)


def test_rulequant_golden() -> None:
    rendered = _render()
    if not GOLDEN.exists():
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_bytes(rendered)
        import pytest

        pytest.skip(f"golden created at {GOLDEN}; rerun to compare")
    assert _stable(rendered) == _stable(GOLDEN.read_bytes())


def test_rulequant_is_stable_across_calls() -> None:
    assert _render() == _render()


def test_software_version_is_recorded() -> None:
    from p2s import __version__

    assert f"<software>p2s {__version__}</software>".encode() in _render()
