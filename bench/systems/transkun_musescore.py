"""Baseline system: Transkun performance MIDI → MuseScore 4 import (spec §6.3)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from p2s.render.pdf import musescore_invocation


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
    invocation = musescore_invocation(performance_mid, out_musicxml)
    if invocation is None:
        return _via_music21(performance_mid, out_musicxml)
    command, env = invocation
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout_s, check=False, env=env
        )
    except subprocess.TimeoutExpired:
        return _via_music21(performance_mid, out_musicxml)
    if proc.returncode == 0 and out_musicxml.exists() and out_musicxml.stat().st_size > 0:
        return True
    return _via_music21(performance_mid, out_musicxml)
