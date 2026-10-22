"""Engine contract tests (spec §5.8, plan Step 6).

Every engine must produce schema-valid output, keep times inside the audio,
survive silent and tiny inputs, be deterministic, and report complete info().
GPU tests are marked `gpu`; the sidecar test is marked `sidecar` and skipped when
no server is reachable.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from p2s.core.config import load_config
from p2s.core.ingest import decode
from p2s.core.schemas import (
    AMTOptions,
    AudioRef,
    BeatGrid,
    EngineInfo,
    IngestOptions,
    MeterHints,
    Performance,
    ScoreOptions,
)
from p2s.engines.registry import create_engine

HAS_CUDA = os.environ.get("CUDA_VISIBLE_DEVICES", "unset") != ""


def _audio(path: Path, tmp: Path) -> AudioRef:
    return decode(path, tmp / "a.wav", IngestOptions())


def _assert_info(info: EngineInfo) -> None:
    assert info.id and info.version
    assert info.code_license and info.weight_license
    assert info.commercial_use in ("yes", "no", "unknown")
    assert info.schema_version == "1.0"


@pytest.mark.gpu
def test_transkun_contract(smoke_audio: Path, tmp_path: Path) -> None:
    engine = create_engine(load_config(), "amt", "transkun_v2", device="cuda")
    _assert_info(engine.info())
    audio = _audio(smoke_audio, tmp_path)
    perf: Performance = engine.transcribe(audio, AMTOptions(device="cuda"))
    assert perf.notes
    for note in perf.notes:
        assert 21 <= note.pitch <= 108
        assert audio.origin_offset_s - 1e-6 <= note.onset <= audio.origin_offset_s + audio.duration_s + 1e-3
        assert note.offset >= note.onset
    again = engine.transcribe(audio, AMTOptions(device="cuda"))
    assert [n.model_dump() for n in again.notes] == [n.model_dump() for n in perf.notes]
    engine.close()


@pytest.mark.gpu
def test_beat_this_contract(smoke_audio: Path, tmp_path: Path) -> None:
    engine = create_engine(load_config(), "beats", "beat_this")
    _assert_info(engine.info())
    audio = _audio(smoke_audio, tmp_path)
    grid: BeatGrid = engine.track(audio, MeterHints())
    assert grid.beats
    assert all(
        audio.origin_offset_s - 1e-6 <= b <= audio.origin_offset_s + audio.duration_s + 1e-3
        for b in grid.beats
    )
    assert set(grid.downbeats) <= set(grid.beats) | {grid.beats[0]}
    engine.close()


@pytest.mark.gpu
def test_transkun_handles_silence_and_tiny_clips(tmp_path: Path) -> None:
    pytest.importorskip("pydub")
    import numpy as np
    import soundfile as sf

    engine = create_engine(load_config(), "amt", "transkun_v2", device="cuda")
    for name, _seconds, data in (
        ("silence.wav", 3.0, np.zeros(3 * 44100, dtype=np.float32)),
        ("tiny.wav", 0.2, np.zeros(int(0.2 * 44100), dtype=np.float32)),
    ):
        path = tmp_path / name
        sf.write(path, data, 44100)
        audio = decode(path, tmp_path / f"{name}.decoded.wav", IngestOptions())
        perf = engine.transcribe(audio, AMTOptions(device="cuda"))
        assert isinstance(perf, Performance)
    engine.close()


@pytest.mark.sidecar
def test_m2st_sidecar_contract(tmp_path: Path) -> None:
    import httpx

    url = os.environ.get("P2S_M2ST_URL", "http://127.0.0.1:8002")
    try:
        httpx.get(f"{url}/v1/health", timeout=2.0).raise_for_status()
    except Exception:
        pytest.skip("M2ST sidecar is not running")
    from p2s.core.schemas import NoteEvent

    config = load_config()
    entry = config.engines.engines["score"]["m2st"]
    entry.url = url
    engine = create_engine(config, "score", "m2st")
    info = engine.info()
    _assert_info(info)
    note = EngineInfo(id="t", version="1", code_license="MIT", weight_license="MIT")
    perf = Performance(
        notes=[
            NoteEvent(pitch=p, onset=i * 0.5, offset=i * 0.5 + 0.45, velocity=80)
            for i, p in enumerate([60, 64, 67, 72, 60, 64, 67, 72])
        ],
        engine=note,
    )
    grid = BeatGrid(
        beats=[i * 0.5 for i in range(10)],
        downbeats=[0.0, 2.0, 4.0],
        time_signatures=[(0.0, "4/4")],
        tempo_bpm=[(0.0, 120.0)],
        engine=note,
    )
    doc = engine.build(perf, grid, ScoreOptions())
    assert doc.musicxml.startswith(b"<?xml")
    assert b"score-partwise" in doc.musicxml
    engine.close()
