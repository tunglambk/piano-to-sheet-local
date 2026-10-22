"""S5 alternative — PM2S (bench-only; not on the default path, D-004).

PM2S takes performance MIDI instead of the in-memory `Performance`, so the
adapter writes a temporary MIDI, runs the CRNN-joint converter, and renders the
resulting score MIDI to MusicXML with MuseScore. Optional dependency: the module
raises a clear error when the PM2S checkout or weights are missing.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from p2s.core.config import REPO_ROOT, EngineSpec, ModelLockEntry
from p2s.core.errors import EngineError
from p2s.core.schemas import BeatGrid, Performance, ScoreDoc, ScoreOptions
from p2s.engines.base import EngineBase
from p2s.render.midi import performance_midi
from p2s.render.pdf import find_musescore

PM2S_ROOT = REPO_ROOT / "data" / "datasets" / "pm2s"


class PM2S(EngineBase):
    def __init__(self, spec: EngineSpec, lock: ModelLockEntry, device: str = "cpu") -> None:
        super().__init__("pm2s", spec, lock, device)
        self._processor = None

    def _load(self) -> None:
        if not (PM2S_ROOT / "pm2s").exists():
            raise EngineError("PM2S is not installed (data/datasets/pm2s missing)")
        import sys

        sys.path.insert(0, str(PM2S_ROOT))
        import torch

        original = torch.load
        torch.load = lambda *a, **k: original(*a, **{**k, "weights_only": False})  # type: ignore[assignment]
        from pm2s import CRNNJointPM2S  # type: ignore[reportMissingImports, reportAttributeAccessIssue]

        self._processor = CRNNJointPM2S(notes_per_beat=[1, 6, 8], ticks_per_beat=480)

    def _version(self) -> str:
        return "pm2s-v1.1"

    def build(self, perf: Performance, grid: BeatGrid, opts: ScoreOptions) -> ScoreDoc:
        self.load()
        musescore = find_musescore()
        if musescore is None:
            raise EngineError("PM2S needs MuseScore to render its score MIDI to MusicXML")
        with tempfile.TemporaryDirectory() as tmp:
            midi_path = Path(tmp) / "performance.mid"
            midi_path.write_bytes(performance_midi(perf, grid))
            score_mid = Path(tmp) / "score.mid"
            assert self._processor is not None
            self._processor.convert(
                str(midi_path), str(score_mid), start_time=0, end_time=perf.notes[-1].offset + 5.0
            )
            out = Path(tmp) / "score.musicxml"
            subprocess.run(
                [str(musescore), "-o", str(out), str(score_mid)],
                check=True,
                capture_output=True,
                timeout=180,
                env={"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin"},
            )
            return ScoreDoc(musicxml=out.read_bytes(), warnings=["PM2S output rendered via MuseScore import"])
