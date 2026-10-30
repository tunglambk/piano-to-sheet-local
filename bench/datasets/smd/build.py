#!/usr/bin/env python3
"""Build the Saarland Music Data (SMD-piano v2) note-level evaluation set.

Zenodo record 13753319 ships, per piece, a real recording (`wav_44100_stereo/`),
the Disklavier performance MIDI (`midi/`) and a CSV with one row per note in audio
time (`Start;Duration;Pitch;Velocity`). SMD has **no score**, so it feeds the
note-level metric (L2) and not the sheet metric: items carry a recording and a
reference performance, and no `score.musicxml` (D-082).

    python bench/datasets/smd/build.py [--source DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
from pathlib import Path

import pretty_midi
import soundfile

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = REPO / "data" / "datasets" / "smd" / "extracted"
DEFAULT_OUT = REPO / "data" / "bench" / "datasets" / "smd_piano"
SPLIT = REPO / "bench" / "splits" / "smd_piano_v0.json"


def _reference_from_csv(path: Path, dst: Path) -> int:
    midi = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    piano = pretty_midi.Instrument(program=0, name="piano")
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle, delimiter=";"):
            try:
                start = float(row["Start"])
                duration = float(row["Duration"])
                pitch = int(float(row["Pitch"]))
            except (KeyError, TypeError, ValueError):
                continue
            piano.notes.append(
                pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=start + max(0.05, duration))
            )
    midi.instruments.append(piano)
    midi.write(str(dst))
    return len(piano.notes)


def build(source: Path, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    items: list[dict] = []
    for csv_path in sorted((source / "csv").glob("*.csv")):
        stem = csv_path.stem
        wav_path = source / "wav_44100_stereo" / f"{stem}.wav"
        if not wav_path.exists():
            continue
        item_id = stem.lower().replace("-smd", "")
        item_dir = out / item_id
        item_dir.mkdir(exist_ok=True)
        shutil.copyfile(wav_path, item_dir / "audio.wav")
        notes = _reference_from_csv(csv_path, item_dir / "performance.mid")
        meta = {
            "item_id": item_id,
            "condition": "real",
            "duration_s": float(soundfile.info(str(wav_path)).duration),
            "source": "SMD-piano v2 (Zenodo 13753319), CC BY-NC-SA 3.0",
            "reference_notes": notes,
            "has_score": False,
        }
        (item_dir / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
        items.append({"item_id": item_id, "path": str(item_dir.relative_to(REPO)), "condition": "real"})
    (out / "items.json").write_text(json.dumps(items, indent=1) + "\n")
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
