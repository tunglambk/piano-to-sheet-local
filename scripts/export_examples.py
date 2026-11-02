#!/usr/bin/env python3
"""Render a few sample sheets into `data/exports/` (D-109).

Every example pairs one item from a public evaluation set with the artefacts the
pipeline produces: the MuseScore PDF, the MusicXML, the compressed `.mxl`, the
performed MIDI and the SVG pages. Outputs stay out of git (they are generated), so
this script is the reproducible way to get them back.

    python scripts/export_examples.py            # all three examples
    python scripts/export_examples.py --only maps_albeniz_espana
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from p2s.core.config import load_config
from p2s.core.pipeline import Pipeline

REPO = Path(__file__).resolve().parents[1]
OUT_ROOT = REPO / "data" / "exports"


def _examples() -> list[dict]:
    smd = json.loads((REPO / "data" / "bench" / "datasets" / "smd_piano" / "items.json").read_text())
    return [
        {
            "name": "p2s_open_liszt_lacampanella",
            "path": REPO / "data" / "p2s_open" / "v0" / "liszt_001_clean",
            "title": "La Campanella",
            "composer": "Franz Liszt",
            "source": "P2S-Open (synthetic audio)",
        },
        {
            "name": "maps_albeniz_espana",
            "path": REPO / "data" / "bench" / "datasets" / "maps_cl" / "alb_se2",
            "title": "España (Albéniz)",
            "composer": "Isaac Albéniz",
            "source": "MAPS (real recording)",
        },
        {
            "name": "smd_bach_bwv849_prelude",
            "path": REPO / smd[0]["path"],
            "title": "Prelude BWV 849",
            "composer": "J. S. Bach",
            "source": "SMD (real recording)",
        },
    ]


def export(example: dict, preset: str = "accurate") -> Path:
    pipeline = Pipeline(load_config(), REPO / "data", job_id=f"export-{example['name']}")
    result = pipeline.run(
        (example["path"] / "audio.wav").resolve(),
        preset,
        title=example["title"],
        composer=example["composer"],
    )
    target = OUT_ROOT / example["name"]
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for artifact, suffix in (
        ("score.pdf", ".pdf"),
        ("score.musicxml", ".musicxml"),
        ("score.mxl", ".mxl"),
        ("performance.mid", ".mid"),
    ):
        shutil.copyfile(result.artifact(artifact), target / f"{example['name']}{suffix}")
    svg_dir = Path(result.artifact("score.pdf")).parent / "svg"
    for page in sorted(svg_dir.glob("*.svg")):
        shutil.copyfile(page, target / page.name)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None, help="export a single example by name")
    parser.add_argument("--preset", default="accurate", choices=["accurate", "fast"])
    args = parser.parse_args()
    written = 0
    for example in _examples():
        if args.only and example["name"] != args.only:
            continue
        target = export(example, args.preset)
        pages = len(list(target.glob("*.svg")))
        size = (target / f"{example['name']}.pdf").stat().st_size // 1024
        print(f"{example['name']}: {example['source']} → {target.relative_to(REPO)} ({size} KB, {pages} SVG)")
        written += 1
    print(f"{written} example(s) written under {OUT_ROOT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
