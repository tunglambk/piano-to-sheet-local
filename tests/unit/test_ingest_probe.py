"""S0 probe falls back to soundfile when ffprobe is absent (D-046)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import soundfile

from p2s.core import ingest


def test_soundfile_fallback_reports_media_info(tmp_path: Path) -> None:
    path = tmp_path / "clip.wav"
    soundfile.write(path, np.zeros((4410, 2), dtype="float32"), 44100)
    info = ingest._probe_with_soundfile(path)
    assert info.sample_rate == 44100
    assert info.channels == 2
    assert info.duration_s == pytest.approx(0.1, abs=0.01)


def test_missing_ffprobe_uses_the_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "clip.wav"
    soundfile.write(path, np.zeros((2205, 1), dtype="float32"), 44100)
    monkeypatch.setattr(ingest.shutil, "which", lambda name: None if name == "ffprobe" else "/usr/bin/x")
    info = ingest.probe(path)
    assert info.channels == 1
