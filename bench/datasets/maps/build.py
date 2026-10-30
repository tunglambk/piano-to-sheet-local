#!/usr/bin/env python3
"""Build the MAPS evaluation set (Zenodo record 18160555, `ENSTDkCl/MUS`).

Each MAPS music piece ships three files: the recording (`.wav`), the **score**
rendered as MIDI (`.mid`, already aligned to the audio — its first note starts at
the same time as the first annotated onset) and a note annotation (`.txt`:
onset, offset and MIDI pitch in audio time).

The builder writes one item per piece in the benchmark's item schema:

    audio.wav        the recording
    score.musicxml   the score MIDI converted to MusicXML — the ground-truth sheet
    performance.mid  the same MIDI, used as the note-level reference
    meta.json        duration, measure count, note count, metre note

MAPS ships no time signature, so the converted score gets music21's default metre
and the truth bar lines are that score's own measure onsets. The report must say
so (D-084).

    python bench/datasets/maps/build.py [--source DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import mido
import soundfile
from music21 import converter

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = REPO / "data" / "datasets" / "maps" / "extracted" / "ENSTDkCl" / "MUS"
DEFAULT_OUT = REPO / "data" / "bench" / "datasets" / "maps_cl"
SPLIT = REPO / "bench" / "splits" / "maps_cl_v0.json"


def _performance_from_annotation(txt_path: Path, dst: Path) -> int:
    """Write the note annotation as a MIDI reference in audio time.

    The MAPS `.mid` is the *score* played at one constant tempo, while the recording
    is a human performance: only the `.txt` annotation carries the real onsets in
    audio seconds. Comparing a transcription against the `.mid` therefore measures
    tempo drift, not note accuracy (D-084).
    """
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    piano = pretty_midi.Instrument(program=0, name="piano")
    with txt_path.open() as handle:
        next(handle, None)
        for line in handle:
            parts = line.split()
            if len(parts) < 3:
                continue
            onset, offset, pitch = (float(parts[0]), float(parts[1]), int(float(parts[2])))
            if offset <= onset:
                offset = onset + 0.05
            piano.notes.append(pretty_midi.Note(velocity=80, pitch=pitch, start=onset, end=offset))
    midi.instruments.append(piano)
    midi.write(str(dst))
    return len(piano.notes)


def _normalise_midi(src: Path, dst: Path, ticks_per_beat: int = 480) -> None:
    """Re-write a MIDI at a normal resolution, keeping the timing.

    MAPS ships `ticks_per_beat = 32767`, which makes the absolute tick count large
    enough that pretty_midi declares the file corrupt. Scaling every delta tick
    preserves the music (and the tempo events) while giving a sane file.
    """
    original = mido.MidiFile(str(src))
    scale = ticks_per_beat / original.ticks_per_beat
    out = mido.MidiFile(ticks_per_beat=ticks_per_beat)
    for track in original.tracks:
        new_track = mido.MidiTrack()
        for message in track:
            new_track.append(message.copy(time=int(round(message.time * scale))))
        out.tracks.append(new_track)
    out.save(str(dst))


def build(source: Path, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    for mid_path in sorted(source.glob("*.mid")):
        wav_path = source / f"{mid_path.stem}.wav"
        if not wav_path.exists():
            continue
        item_id = mid_path.name.replace("MAPS_MUS-", "").replace("_ENSTDkCl.mid", "").lower()
        item_dir = out / item_id
        item_dir.mkdir(exist_ok=True)
        shutil.copyfile(wav_path, item_dir / "audio.wav")
        score = converter.parse(str(mid_path))
        score.write("musicxml", fp=str(item_dir / "score.musicxml"))
        # MAPS ships ticks_per_beat = 32767, which pretty_midi rejects as corrupt
        # ("largest tick ... likely corrupt"), so the reference is re-exported with
        # a normal resolution (D-084).
        txt_path = source / f"{mid_path.stem}.txt"
        reference_notes = 0
        if txt_path.exists():
            reference_notes = _performance_from_annotation(txt_path, item_dir / "performance.mid")
        else:
            _normalise_midi(mid_path, item_dir / "performance.mid")
        measures = len(score.parts[0].getElementsByClass("Measure"))
        notes = len(score.recurse().notes)
        meta = {
            "item_id": item_id,
            "condition": "real",
            "duration_s": float(soundfile.info(str(wav_path)).duration),
            "source": "MAPS v0.4, ENSTDkCl/MUS (Zenodo 18160555), CC BY-NC-SA 2.0",
            "measures": measures,
            "notes": notes,
            "metre": "music21 default; MAPS ships no time signature",
            "reference_notes": reference_notes,
        }
        (item_dir / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
        items.append({"item_id": item_id, "path": str(item_dir.relative_to(REPO)), "condition": "real"})
    (out / "items.json").write_text(json.dumps(items, indent=1) + "\n")
    # Freeze 60/40 dev/test once; the manifest must not change afterwards (D-010).
    if not SPLIT.exists():
        ids = [entry["item_id"] for entry in items]
        cut = max(1, round(0.6 * len(ids)))
        SPLIT.parent.mkdir(parents=True, exist_ok=True)
        SPLIT.write_text(json.dumps({"dev": ids[:cut], "test": ids[cut:]}, indent=1) + "\n")
    return items


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    built = build(args.source, args.out)
    print(f"built {len(built)} items into {args.out}")
