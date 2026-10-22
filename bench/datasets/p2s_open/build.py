"""P2S-Open v0 builder (D-015): `clean` and `phone` conditions, seeded.

Phase 1 renders license-cleared ASAP scores with their *real* performance MIDI
(the human timing), through FluidSynth + the MIT "MS Basic" soundfont. That is
the expressive layer for v0; D-015's synthesised performance model lands in P3a
when `mixed` arrives. Ground truth is exact: the ASAP MusicXML score, the
performance MIDI and the ASAP beat annotations, all copied into the item.

Phone condition: band limit (300–3400 Hz), compression, seeded noise and a lossy
MP3 round trip. Everything is deterministic for a given seed and source.

    python bench/datasets/p2s_open/build.py --sources 52 --out data/p2s_open/v0
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ASAP = REPO / "data" / "datasets" / "asap-dataset"
ACPAS = REPO / "data" / "datasets" / "ACPAS-dataset"
SOUNDFONT = REPO / ".tools" / "mscore" / "share" / "mscore4portable-4.7" / "sound" / "MS Basic.sf3"
FLUIDSYNTH = REPO / ".envs" / "base" / "bin" / "fluidsynth"
SEED = 20261021
TEST_PIECE_IDS = {15, 78, 159, 172, 254, 288, 322, 374, 395, 399, 411, 418, 452, 478}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return float(out)


def select_sources(count: int, seed: int) -> list[dict]:
    with open(ASAP / "metadata.csv") as fh:
        rows = list(csv.DictReader(fh))
    with open(ACPAS / "metadata_R.csv") as fh:
        acpas = {
            r["performance_MIDI_external"].replace("{ASAP}/", ""): int(r["piece_id"])
            for r in csv.DictReader(fh)
            if r["source"] == "ASAP"
        }
    candidates = []
    for row in rows:
        midi = row["midi_performance"]
        piece_id = acpas.get(midi)
        if piece_id is None or piece_id in TEST_PIECE_IDS:
            continue
        midi_path = ASAP / midi
        score_path = ASAP / row["xml_score"]
        if not (midi_path.exists() and score_path.exists()):
            continue
        candidates.append(
            {
                "composer": row["composer"],
                "title": row["title"],
                "folder": row["folder"],
                "midi": midi,
                "score": row["xml_score"],
                "beats": row["performance_annotations"],
                "piece_id": piece_id,
            }
        )
    candidates.sort(key=lambda c: (c["composer"], c["folder"], c["midi"]))
    rng = random.Random(seed)
    by_composer: dict[str, list[dict]] = {}
    for candidate in candidates:
        by_composer.setdefault(candidate["composer"], []).append(candidate)
    composers = sorted(by_composer)
    rng.shuffle(composers)
    picked: list[dict] = []
    index = 0
    while len(picked) < count and composers:
        composer = composers[index % len(composers)]
        pool = by_composer[composer]
        if pool:
            picked.append(pool.pop(rng.randrange(len(pool))))
        index += 1
        if index > count * 20:
            break
    return picked[:count]


def render_clean(midi: Path, out_wav: Path) -> None:
    run(
        [
            str(FLUIDSYNTH),
            "-ni",
            "-q",
            "-a",
            "file",
            "-F",
            str(out_wav),
            "-r",
            "44100",
            "-g",
            "0.8",
            str(SOUNDFONT),
            str(midi),
        ]
    )


def make_phone(clean: Path, out_wav: Path, rng: random.Random, tmp: Path) -> None:
    noise_db = -38 + rng.random() * 4
    mp3 = tmp / "phone.mp3"
    duration = probe_duration(clean)
    amplitude = 10 ** (noise_db / 20)
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(clean),
            "-f",
            "lavfi",
            "-i",
            f"anoisesrc=color=pink:amplitude={amplitude:.5f}:duration={duration:.3f}"
            f":seed={rng.randrange(1, 10**6)}",
            "-filter_complex",
            "[0:a]highpass=f=300,lowpass=f=3400,acompressor=threshold=0.1:ratio=3:attack=5:release=80,volume=2dB[voice];"
            "[voice][1:a]amix=inputs=2:duration=first:weights=1 0.08[out]",
            "-map",
            "[out]",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(tmp / "filtered.wav"),
        ]
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(tmp / "filtered.wav"),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "64k",
            str(mp3),
        ]
    )
    run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(mp3),
            "-ar",
            "44100",
            "-ac",
            "2",
            str(out_wav),
        ]
    )


def beats_in_window(beats: list[float], downbeats: list[float], start: float, end: float) -> dict:
    return {
        "beats": [round(b - start, 6) for b in beats if start <= b < end],
        "downbeats": [round(b - start, 6) for b in downbeats if start <= b < end],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", type=int, default=52)
    ap.add_argument("--out", default="data/p2s_open/v0")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    out = REPO / args.out
    out.mkdir(parents=True, exist_ok=True)
    annotations = json.loads((ASAP / "asap_annotations.json").read_text())
    sources = select_sources(args.sources, args.seed)
    print(f"selected {len(sources)} sources")
    rng = random.Random(args.seed)
    registry = []
    for index, source in enumerate(sources):
        midi = ASAP / source["midi"]
        import pretty_midi

        duration = pretty_midi.PrettyMIDI(str(midi)).get_end_time()
        length = min(75.0, max(40.0, duration - 10.0))
        start = min(duration * 0.2, max(0.0, duration - length - 1.0))
        item_base = f"{source['composer'].lower()}_{index:03d}"
        ann = annotations.get(source["midi"], {})
        beats = [float(b) for b in ann.get("performance_beats", [])]
        downbeats = [float(b) for b in ann.get("performance_downbeats", [])]
        work = out / ".work"
        work.mkdir(exist_ok=True)
        full = work / f"{item_base}.wav"
        render_clean(midi, full)
        excerpt = work / f"{item_base}_excerpt.wav"
        run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{length:.3f}",
                "-i",
                str(full),
                "-ar",
                "44100",
                "-ac",
                "2",
                str(excerpt),
            ]
        )
        for condition in ("clean", "phone"):
            item_id = f"{item_base}_{condition}"
            item_dir = out / item_id
            item_dir.mkdir(parents=True, exist_ok=True)
            tmp = item_dir / ".tmp"
            tmp.mkdir(exist_ok=True)
            run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{length:.3f}",
                    "-i",
                    str(full),
                    "-ar",
                    "44100",
                    "-ac",
                    "2",
                    str(excerpt),
                ]
            )
            if condition == "clean":
                shutil.copyfile(excerpt, item_dir / "audio.wav")
            else:
                make_phone(excerpt, item_dir / "audio.wav", rng, tmp)
            shutil.copyfile(ASAP / source["score"], item_dir / "score.musicxml")
            shutil.copyfile(midi, item_dir / "performance.mid")
            # v0 is a dev-only build: 25% sampling would leave too few dev items.
            # P3a freezes the dev/test split when it adds `mixed` and the full size (D-010).
            split = "dev"
            meta = {
                "item_id": item_id,
                "condition": condition,
                "split": split,
                "source": "asap",
                "source_tag": "asap",
                "license": "CC BY-NC-SA 4.0",
                "composer": source["composer"],
                "title": source["title"],
                "folder": source["folder"],
                "piece_id": source["piece_id"],
                "start_s": round(start, 3),
                "duration_s": round(length, 3),
                "seed": args.seed,
                "beats": beats_in_window(beats, downbeats, start, start + length),
                "ground_truth": {"score": "score.musicxml", "midi": "performance.mid"},
            }
            (item_dir / "meta.json").write_text(json.dumps(meta, sort_keys=True, indent=1) + "\n")
            shutil.rmtree(tmp, ignore_errors=True)
            registry.append(
                {
                    "item_id": item_id,
                    "split": split,
                    "condition": condition,
                    "source": "asap",
                    "license": "CC BY-NC-SA 4.0",
                    "path": str(item_dir.relative_to(REPO)),
                }
            )
            print(f"  {item_id} {condition} {split} {length:.0f}s")
    shutil.rmtree(out / ".work", ignore_errors=True)
    (out / "items.json").write_text(json.dumps(registry, indent=1) + "\n")
    dev = [r for r in registry if r["split"] == "dev"]
    print(f"wrote {len(registry)} items ({len(dev)} dev) -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
