"""S0 ingest: containers, ranges and error types (FR-01)."""

from __future__ import annotations

from pathlib import Path

import pytest

from p2s.core.errors import CorruptInput, UnsupportedInput
from p2s.core.ingest import decode
from p2s.core.schemas import IngestOptions


def test_decodes_wav_to_44k_stereo(smoke_audio: Path, tmp_path: Path) -> None:
    ref = decode(smoke_audio, tmp_path / "a.wav", IngestOptions())
    assert (ref.sample_rate, ref.channels) == (44100, 2)
    assert ref.origin_offset_s == 0.0
    assert ref.duration_s > 1.0


def test_range_keeps_original_time_origin(smoke_audio: Path, tmp_path: Path) -> None:
    ref = decode(smoke_audio, tmp_path / "b.wav", IngestOptions(start_s=1.0, end_s=3.0))
    assert ref.origin_offset_s == 1.0
    assert 1.5 < ref.duration_s < 2.5
    assert ref.to_original(0.5) == 1.5


def test_container_inputs_decode(smoke_manifest: dict, repo_root: Path, tmp_path: Path) -> None:
    for name in ("scale_c_major.mp4", "scale_c_major.m4a", "scale_c_major.webm"):
        info = smoke_manifest.get(name)
        if not info or not (repo_root / info["path"]).exists():
            pytest.skip(f"{name} fixture missing (fixtures are generated locally)")
        ref = decode(repo_root / info["path"], tmp_path / f"{name}.wav", IngestOptions())
        assert ref.duration_s > 5.0


def test_corrupt_file_is_typed(tmp_path: Path) -> None:
    bad = tmp_path / "bad.mp3"
    bad.write_bytes(b"not audio")
    with pytest.raises((CorruptInput, UnsupportedInput)):
        decode(bad, tmp_path / "out.wav", IngestOptions())


def test_missing_file_is_typed(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedInput):
        decode(tmp_path / "missing.wav", tmp_path / "out.wav", IngestOptions())


def test_range_beyond_duration_is_rejected(smoke_audio: Path, tmp_path: Path) -> None:
    with pytest.raises(UnsupportedInput):
        decode(smoke_audio, tmp_path / "c.wav", IngestOptions(start_s=10_000.0))
