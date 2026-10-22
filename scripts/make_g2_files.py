#!/usr/bin/env python3
"""Build the 10 files used by the G2 browser flow (plan step 10, D-016).

Five MAESTRO validation recordings, each transcoded to a different container, and
five P2S-Open dev items (three `clean`, two `phone`). Everything is a 90-second
excerpt so the browser run stays short; the formats, not the length, are what G2
checks.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "g2"
LIST = REPO / "apps" / "web" / "e2e" / "g2-files.json"
FORMATS = [("mp3", "libmp3lame"), ("m4a", "aac"), ("webm", "vorbis"), ("flac", "flac"), ("mp4", "aac")]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def maestro_picks(count: int) -> list[Path]:
    manifest = json.loads((REPO / "data" / "datasets" / "maestro-selection.json").read_text())
    paths = [
        REPO / meta["path"]
        for meta in manifest.values()
        if meta.get("role") == "smoke_validation" and (REPO / meta["path"]).exists()
    ]
    return paths[:count]


def p2s_open_picks() -> list[Path]:
    index = json.loads((REPO / "data" / "p2s_open" / "v0" / "items.json").read_text())
    dev = [entry for entry in index if entry["split"] == "dev"]
    clean = [entry for entry in dev if entry["condition"] == "clean"][:3]
    phone = [entry for entry in dev if entry["condition"] == "phone"][:2]
    return [REPO / entry["path"] / "audio.wav" for entry in clean + phone]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    entries = []
    for path, (extension, codec) in zip(maestro_picks(5), FORMATS, strict=False):
        target = OUT / f"maestro_{path.stem[:28]}.{extension}"
        if not target.exists():
            extra = ["-strict", "-2"] if codec == "vorbis" else []
            run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-ss",
                    "20",
                    "-t",
                    "90",
                    "-i",
                    str(path),
                    "-c:a",
                    codec,
                    *extra,
                    "-b:a",
                    "128k",
                    str(target),
                ]
            )
        entries.append({"label": f"maestro {extension}", "path": str(target), "kind": "maestro"})
    for path in p2s_open_picks():
        target = OUT / f"open_{path.parent.name}.wav"
        if not target.exists():
            shutil.copyfile(path, target)
        entries.append({"label": f"p2s-open {path.parent.name}", "path": str(target), "kind": "p2s_open"})

    LIST.write_text(json.dumps(entries, indent=1) + "\n")
    print(f"wrote {len(entries)} files, list at {LIST.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
