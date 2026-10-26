"""Pipeline cache behaviour with fake engines (G1: cache criterion)."""

from __future__ import annotations

from pathlib import Path

import pytest

import p2s.core.pipeline as pipeline_module
from p2s.core.config import load_config
from p2s.core.pipeline import Pipeline
from p2s.core.schemas import BeatGrid, EngineInfo, NoteEvent, Performance, ScoreOptions


def _info(engine_id: str) -> EngineInfo:
    return EngineInfo(id=engine_id, version="test", code_license="MIT", weight_license="MIT")


class FakeAMT:
    def info(self) -> EngineInfo:
        return _info("fake_amt")

    def transcribe(self, audio, opts) -> Performance:  # noqa: ANN001
        notes = []
        for i, pitch in enumerate([60, 62, 64, 65, 67, 69, 71, 72]):
            notes.append(
                NoteEvent(
                    pitch=pitch,
                    onset=audio.origin_offset_s + i * 0.25,
                    offset=audio.origin_offset_s + i * 0.25 + 0.2,
                    velocity=80,
                )
            )
        return Performance(notes=notes, engine=self.info())

    def close(self) -> None:
        return None


class FakeBeats:
    def info(self) -> EngineInfo:
        return _info("fake_beats")

    def track(self, audio, hints) -> BeatGrid:  # noqa: ANN001
        beats = [audio.origin_offset_s + i * 0.25 for i in range(16)]
        return BeatGrid(
            beats=beats,
            downbeats=beats[::4],
            time_signatures=[(beats[0], "4/4")],
            tempo_bpm=[(beats[0], 240.0)],
            engine=self.info(),
        )

    def close(self) -> None:
        return None


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    real = pipeline_module.create_engine

    def fake_create(config, stage, name, device=None):  # noqa: ANN001
        if stage == "amt":
            return FakeAMT()
        if stage == "beats":
            return FakeBeats()
        return real(config, stage, name, device)

    def fake_pdf(musicxml, out_pdf, svg_pages=None, timeout_s=180.0):  # noqa: ANN001
        Path(out_pdf).write_bytes(b"%PDF-1.4\n%fake\n")
        return type("R", (), {"path": out_pdf, "engine": "fake", "warnings": []})()

    monkeypatch.setattr(pipeline_module, "create_engine", fake_create)
    monkeypatch.setattr(pipeline_module, "render_pdf", fake_pdf)


def _run(data_dir: Path, audio: Path, score_opts: ScoreOptions | None = None):  # noqa: ANN001
    pipeline = Pipeline(load_config(), data_dir, job_id="test")
    return pipeline.run(audio, "fast", score_opts=score_opts or ScoreOptions())


def test_second_run_hits_every_stage(patched: None, tmp_path: Path, smoke_audio: Path) -> None:
    first = _run(tmp_path, smoke_audio)
    assert first.artifact("score.musicxml").exists()
    second = _run(tmp_path, smoke_audio)
    hits = [s["cache"] for s in second.run["stages"]]
    assert hits and all(h == "hit" for h in hits)


def test_changing_s5_params_reuses_s0_to_s4(patched: None, tmp_path: Path, smoke_audio: Path) -> None:
    _run(tmp_path, smoke_audio, ScoreOptions(quantize_grid="1/16"))
    second = _run(tmp_path, smoke_audio, ScoreOptions(quantize_grid="1/8"))
    by_stage = {s["stage"]: s["cache"] for s in second.run["stages"]}
    for stage in ("s0_ingest", "s1_route", "s3_amt", "s4_beats"):
        assert by_stage[stage] == "hit", stage
    for stage in ("s5_score", "s6_post", "s7_align", "s8_render"):
        assert by_stage[stage] == "miss", stage


def test_manifest_is_deterministic(patched: None, tmp_path: Path, smoke_audio: Path) -> None:
    first = _run(tmp_path, smoke_audio)
    second = _run(tmp_path / "other", smoke_audio)
    assert first.manifest == second.manifest
    assert "git_commit" in first.manifest
    assert first.manifest["warnings"] == []


def test_unreachable_score_engine_falls_back(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, smoke_audio: Path
) -> None:
    """NFR-04: a dead S5 engine still yields a sheet, with a warning."""
    from p2s.engines.sidecar_client import SidecarClient

    class DeadClient(SidecarClient):
        def info(self):
            from p2s.core.errors import EngineError

            raise EngineError("sidecar unreachable (test)")

    real = pipeline_module.create_engine

    def fake_create(config, stage, name, device=None):  # noqa: ANN001
        if stage == "amt":
            return FakeAMT()
        if stage == "beats":
            return FakeBeats()
        if stage == "score" and name == "m2st":
            return DeadClient("m2st", "http://127.0.0.1:9", 5.0)
        return real(config, stage, name, device)

    def fake_pdf(musicxml, out_pdf, svg_pages=None, timeout_s=180.0):  # noqa: ANN001
        Path(out_pdf).write_bytes(b"%PDF-1.4\n%fake\n")
        return type("R", (), {"path": out_pdf, "engine": "fake", "warnings": []})()

    monkeypatch.setattr(pipeline_module, "create_engine", fake_create)
    monkeypatch.setattr(pipeline_module, "render_pdf", fake_pdf)
    pipeline = Pipeline(load_config(), tmp_path, job_id="fallback")
    result = pipeline.run(smoke_audio, "accurate")
    assert result.artifact("score.musicxml").exists()
    assert any("m2st" in w and "falling back" in w for w in result.warnings)


def test_artifacts_are_byte_identical_without_cache(patched: None, tmp_path: Path, smoke_audio: Path) -> None:
    """Determinism (spec §5.3): two cold runs must produce identical bytes."""
    first = _run(tmp_path / "a", smoke_audio)
    second = _run(tmp_path / "b", smoke_audio)
    for kind in ("performance.mid", "score.musicxml"):
        assert first.artifact(kind).read_bytes() == second.artifact(kind).read_bytes(), kind
    timemap_first = first.artifact("timemap.json").read_bytes()
    assert timemap_first == second.artifact("timemap.json").read_bytes()
