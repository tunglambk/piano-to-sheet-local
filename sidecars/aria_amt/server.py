"""Aria-AMT sidecar (S3 second opinion, D-043).

The `accurate` preset lists two AMT engines but only Transkun ever ran: Aria has
no sidecar, so the ensemble silently degraded to a single model. This server
wraps the upstream CLI in a subprocess (it is an isolated, GPU-heavy tool) and
returns a Performance through the standard sidecar contract.

    PYTHONPATH=. .envs/aria/bin/python -m uvicorn sidecars.aria_amt.server:app --port 8001
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

import pretty_midi  # noqa: E402

from p2s.core.schemas import AMTOptions, AudioRef, EngineInfo, NoteEvent, Performance  # noqa: E402
from p2s.engines.sidecar_server import create_app  # noqa: E402

CHECKPOINT = Path(
    os.environ.get(
        "P2S_ARIA_CHECKPOINT", str(REPO / "models" / "aria_amt" / "piano-medium-double-1.0.safetensors")
    )
)
CLI = os.environ.get("P2S_ARIA_CLI", str(REPO / ".envs" / "aria" / "bin" / "aria-amt"))


class AriaEngine:
    def info(self) -> EngineInfo:
        return EngineInfo(
            id="aria_amt",
            version="0.0.1",
            weights_sha256={CHECKPOINT.name: "see configs/models.lock"},
            code_license="MIT",
            weight_license="CC-BY-4.0",
            commercial_use="yes",
            device="cuda",
            kind="sidecar",
        )

    def transcribe(self, audio: AudioRef, _options: AMTOptions | None = None) -> Performance:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            result = subprocess.run(
                [
                    CLI,
                    "transcribe",
                    "medium-double",
                    str(CHECKPOINT),
                    "-load_path",
                    audio.path,
                    "-save_dir",
                    str(out),
                    "-bs",
                    "1",
                ],
                capture_output=True,
                text=True,
                timeout=1800,
                check=False,
            )
            midi_files = sorted(out.rglob("*.mid")) + sorted(out.rglob("*.midi"))
            if result.returncode != 0 or not midi_files:
                raise RuntimeError(f"aria-amt failed ({result.returncode}): {result.stderr[-400:]}")
            midi = pretty_midi.PrettyMIDI(str(midi_files[0]))
            notes = [
                NoteEvent(
                    pitch=int(n.pitch), onset=float(n.start), offset=float(n.end), velocity=int(n.velocity)
                )
                for instrument in midi.instruments
                for n in instrument.notes
            ]
        return Performance(notes=notes, engine=self.info())


app = create_app(AriaEngine())
