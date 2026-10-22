"""M2ST sidecar (S5). Runs the authors' MIDI2ScoreTransformer behind /v1/*.

Local dev:
    PYTHONPATH=<repo> .envs/m2st/bin/python -m uvicorn sidecars.m2st.server:app --port 8002

Docker: see Dockerfile; the checkpoint is mounted read-only from models/.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "data" / "datasets" / "m2st" / "midi2scoretransformer"))
os.environ.setdefault("MPLCONFIGDIR", str(REPO / ".cache" / "mpl"))

import torch  # noqa: E402

from p2s.core.schemas import (  # noqa: E402
    BeatGrid,
    EngineInfo,
    Performance,
    ScoreDoc,
    ScoreOptions,
)
from p2s.engines.sidecar_server import create_app  # noqa: E402
from p2s.render.midi import performance_midi  # noqa: E402

CHECKPOINT = Path(os.environ.get("P2S_M2ST_CHECKPOINT", REPO / "models" / "m2st" / "MIDI2ScoreTF.ckpt"))
DEVICE = os.environ.get("P2S_M2ST_DEVICE", "cuda" if torch.cuda.is_available() else "cpu")


class M2STEngine:
    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None

    def info(self) -> EngineInfo:
        from p2s.core.config import load_config

        try:
            lock = load_config().lock.by_id("m2st")
            code_license = lock.code_license if lock else "unknown"
            weight_license = lock.weight_license if lock else "unknown"
        except Exception:  # noqa: BLE001 - sidecars may run without the repo configs
            code_license = weight_license = "unknown"
        return EngineInfo(
            id="m2st", version="0.0.1", weights_sha256={}, code_license=code_license,
            weight_license=weight_license, commercial_use="unknown", device=DEVICE, kind="sidecar",
        )

    def _load(self) -> None:
        if self._model is not None:
            return
        from models.roformer import Roformer
        from tokenizer import MultistreamTokenizer

        ckpt = torch.load(CHECKPOINT, map_location="cpu", weights_only=False)
        hp = ckpt["hyper_parameters"]
        model = Roformer(
            enc_configuration=hp["enc_configuration"],
            dec_configuration=hp["dec_configuration"],
            hyperparameters=hp["hyperparameters"],
        )
        model.load_state_dict(ckpt["state_dict"])
        self._model = model.to(DEVICE).eval()
        self._tokenizer = MultistreamTokenizer

    def build(self, perf: Performance, grid: BeatGrid, options: ScoreOptions) -> ScoreDoc:
        self._load()
        from utils import infer

        with tempfile.TemporaryDirectory() as tmp:
            midi_path = Path(tmp) / "performance.mid"
            midi_path.write_bytes(performance_midi(perf, grid))
            x = self._tokenizer.tokenize_midi(str(midi_path))
            with torch.no_grad():
                y = infer(x, self._model, overlap=64, chunk=512, verbose=False, kv_cache=True)
            notes = self._tokenizer.midi_to_list(str(midi_path))
            score = self._tokenizer.detokenize_mxl(y, midi_sequence=notes)
            out = Path(tmp) / "score.musicxml"
            score.write("musicxml", fp=str(out))
            return ScoreDoc(musicxml=out.read_bytes(), warnings=[])

    def close(self) -> None:
        self._model = None
        if torch.cuda.is_available():
            torch.cuda.empty_cache()


app = create_app(M2STEngine())
