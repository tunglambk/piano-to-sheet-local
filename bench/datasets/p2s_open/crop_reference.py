#!/usr/bin/env python3
"""Crop each item's reference score to the excerpt the audio covers (D-115).

P2S-Open items are 30–90 s excerpts of a full piece, but the reference
`score.musicxml` shipped with them is the **whole piece**: scoring an excerpt
against it produced 14 608 "entire measure insert/delete" edits on one item, i.e.
the OMR-NED we reported was dominated by the mismatch, not by our errors.

ASAP's `asap_annotations.json` maps every performance downbeat to a score measure
(`downbeats_score_map`), so the excerpt's measure range is recoverable exactly. This
script writes `score_excerpt.musicxml` next to each item.

    python bench/datasets/p2s_open/crop_reference.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree as ET

REPO = Path(__file__).resolve().parents[3]
OPEN = REPO / "data" / "p2s_open" / "v0"
ASAP = REPO / "data" / "datasets" / "asap-dataset" / "asap_annotations.json"


def _performance_key(folder: str, start_s: float, duration_s: float, beats: list[float]) -> str | None:
    """Pick the performance whose beats match the excerpt's (same piece, many takes)."""
    annotations = json.loads(ASAP.read_text())
    best: tuple[float, str] | None = None
    for key, value in annotations.items():
        if not key.startswith(f"{folder}/"):
            continue
        perf_beats = value.get("performance_beats") or []
        window = [b - start_s for b in perf_beats if start_s - 0.02 <= b <= start_s + duration_s + 0.02]
        if len(window) < 4 or not beats:
            continue
        # Compare the first few beat times; the excerpt's beats are relative to it.
        error = sum(abs(window[i] - beats[i]) for i in range(min(4, len(window), len(beats)))) / 4
        if best is None or error < best[0]:
            best = (error, key)
    return best[1] if best and best[0] < 0.25 else None


def crop(item_dir: Path, dry_run: bool = False) -> tuple[int, int] | None:
    meta = json.loads((item_dir / "meta.json").read_text())
    key = _performance_key(
        meta["folder"], float(meta["start_s"]), float(meta["duration_s"]), meta["beats"]["beats"]
    )
    if key is None:
        return None
    value = json.loads(ASAP.read_text())[key]
    downbeats = value["performance_downbeats"]
    measure_of = value["downbeats_score_map"]
    start, duration = float(meta["start_s"]), float(meta["duration_s"])
    inside = [measure_of[i] for i, downbeat in enumerate(downbeats) if start <= downbeat <= start + duration]
    if len(inside) < 2:
        return None
    first, last = min(inside), max(inside)
    # Edit the XML in place: re-exporting through music21 fails on the source's
    # 2048th-note tuplets ("too short for MusicXML"), which the crop must not touch.
    root = ET.fromstring((item_dir / "score.musicxml").read_bytes())
    for part in root.findall("part"):
        measures = part.findall("measure")
        # The attributes (divisions, key, time, clefs) live in the first measure of
        # the piece; a crop that keeps measure 59 first must carry them over, or no
        # importer can read the file (VeroSim parsed 0 notes before this, D-115).
        attributes = None
        for measure in measures:
            found = measure.find("attributes")
            if found is not None:
                attributes = found
                break
        for measure in list(measures):
            raw = measure.get("number") or ""
            if not raw.isdigit():
                continue
            if not first <= int(raw) <= last:
                part.remove(measure)
        remaining = part.findall("measure")
        if remaining and attributes is not None and remaining[0].find("attributes") is None:
            remaining[0].insert(0, ET.fromstring(ET.tostring(attributes)))
    if not dry_run:
        ET.ElementTree(root).write(
            item_dir / "score_excerpt.musicxml", encoding="utf-8", xml_declaration=True
        )
    return first, last


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    index = json.loads((OPEN / "items.json").read_text())
    entries = [entry for entry in index if entry["split"] == "dev"]
    if args.limit:
        entries = entries[: args.limit]
    written = 0
    for entry in entries:
        item_dir = REPO / entry["path"]
        span = crop(item_dir, args.dry_run)
        if span is None:
            print(f"{entry['item_id']}: no performance match")
            continue
        print(f"{entry['item_id']}: measures {span[0]}..{span[1]} ({span[1] - span[0] + 1} bars)")
        written += 1
    print(f"{written}/{len(entries)} reference scores cropped{' (dry run)' if args.dry_run else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
