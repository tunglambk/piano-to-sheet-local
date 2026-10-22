"""Baseline system: Transkun performance MIDI → MuseScore 4 import (spec §6.3)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from p2s.render.pdf import find_musescore


def to_musicxml(performance_mid: Path, out_musicxml: Path, timeout_s: float = 300.0) -> bool:
    mscore = find_musescore()
    if mscore is None:
        return False
    proc = subprocess.run(
        [str(mscore), "-o", str(out_musicxml), str(performance_mid)],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
    )
    return proc.returncode == 0 and out_musicxml.exists()
