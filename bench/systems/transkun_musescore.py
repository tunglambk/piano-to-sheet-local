"""Baseline system: Transkun performance MIDI → MuseScore 4 import (spec §6.3)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from p2s.render.pdf import find_musescore


def _via_music21(performance_mid: Path, out_musicxml: Path) -> bool:
    """Fallback when the MuseScore bundle cannot start (D-040).

    music21 imports the MIDI file and quantises it with default settings, which is
    the naive path a user gets from any notation app. It is a weaker baseline than
    MuseScore's importer, and the report records which one produced a number.
    """
    try:
        from music21 import converter

        score = converter.parse(str(performance_mid))
        score.write("musicxml", fp=str(out_musicxml))
        return out_musicxml.exists()
    except Exception:  # noqa: BLE001 - a missing fallback must not crash the runner
        return False


def to_musicxml(performance_mid: Path, out_musicxml: Path, timeout_s: float = 300.0) -> bool:
    mscore = find_musescore()
    if mscore is None:
        return _via_music21(performance_mid, out_musicxml)
    proc = subprocess.run(
        [str(mscore), "-o", str(out_musicxml), str(performance_mid)],
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        env=dict(os.environ, QT_QPA_PLATFORM="offscreen"),
    )
    if proc.returncode == 0 and out_musicxml.exists():
        return True
    return _via_music21(performance_mid, out_musicxml)
