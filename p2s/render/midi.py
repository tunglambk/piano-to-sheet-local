"""MIDI export: performance MIDI and quantised score MIDI (deterministic)."""

from __future__ import annotations

import io

from p2s.core.schemas import BeatGrid, Performance
from p2s.post.align import ScoreNote


def _tempo(grid: BeatGrid | None) -> float:
    if grid and grid.tempo_bpm:
        return max(20.0, min(300.0, float(grid.tempo_bpm[0][1])))
    return 120.0


def performance_midi(perf: Performance, grid: BeatGrid | None = None) -> bytes:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(resolution=960, initial_tempo=_tempo(grid))
    piano = pretty_midi.Instrument(program=0, name="Piano")
    for note in perf.notes:
        piano.notes.append(
            pretty_midi.Note(velocity=note.velocity, pitch=note.pitch, start=note.onset, end=note.offset)
        )
    for on, off in perf.pedals:
        piano.control_changes.append(pretty_midi.ControlChange(number=64, value=127, time=on))
        piano.control_changes.append(pretty_midi.ControlChange(number=64, value=0, time=off))
    midi.instruments.append(piano)
    buffer = io.BytesIO()
    midi.write(buffer)
    return buffer.getvalue()


def quantized_midi(notes: list[ScoreNote], grid: BeatGrid | None = None) -> bytes:
    import pretty_midi

    bpm = _tempo(grid)
    seconds_per_beat = 60.0 / bpm
    midi = pretty_midi.PrettyMIDI(resolution=960, initial_tempo=bpm)
    piano = pretty_midi.Instrument(program=0, name="Piano")
    for note in notes:
        piano.notes.append(
            pretty_midi.Note(
                velocity=80,
                pitch=note.pitch,
                start=note.beat * seconds_per_beat,
                end=(note.beat + note.duration_beats) * seconds_per_beat,
            )
        )
    midi.instruments.append(piano)
    buffer = io.BytesIO()
    midi.write(buffer)
    return buffer.getvalue()
