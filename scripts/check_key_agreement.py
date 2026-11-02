#!/usr/bin/env python3
"""Compare the engraved key signature with the reference score's (D-104).

A wrong key signature makes every accidental in the piece wrong, so it is worth a
number of its own: this prints the fifths the pipeline chose and the fifths the
reference declares, and reports the agreement rate.

    python scripts/check_key_agreement.py --limit 8
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET

from p2s.core.config import load_config
from p2s.core.pipeline import Pipeline

REPO = Path(__file__).resolve().parents[1]
OPEN = REPO / "data" / "p2s_open" / "v0"


def fifths_of(musicxml: bytes) -> str | None:
    root = ET.fromstring(musicxml)
    for part in root.findall("part"):
        value = part.findtext("measure/attributes/key/fifths")
        if value is not None:
            return value
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--preset", default="accurate")
    parser.add_argument("--data-dir", default=str(REPO / "data"))
    args = parser.parse_args()
    index = json.loads((OPEN / "items.json").read_text())
    entries = [entry for entry in index if entry["split"] == "dev"][: args.limit]
    agree = 0
    total = 0
    for entry in entries:
        item_dir = REPO / entry["path"]
        result = Pipeline(load_config(), Path(args.data_dir), job_id=f"key-{entry['item_id']}").run(
            item_dir / "audio.wav", args.preset
        )
        ours = fifths_of(result.artifact("score.musicxml").read_bytes())
        reference = fifths_of((item_dir / "score.musicxml").read_bytes())
        same = ours == reference
        agree += same
        total += 1
        print(f"{entry['item_id']}: ours {ours} reference {reference} {'ok' if same else 'differs'}")
    print(f"\n{agree}/{total} key signatures agree with the reference")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
