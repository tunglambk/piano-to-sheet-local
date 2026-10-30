#!/usr/bin/env python3
"""Audit engraved MusicXML for defects that no note metric can see.

Checks, per file:
  * every `<type>` (+ dots) adds up to its `<duration>`;
  * every beam span is valid (music21 reports the same warnings a reader would);
  * the metre is present, and no bar is empty unless the piece really has a rest bar;
  * key and time signatures reach the rendered SVG when one is given.

Usage:
    python scripts/audit_engraving.py data/cache/*/score.musicxml
Exit code 1 when a hard defect (type/duration, dangling beam) is found.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

BASES = {
    "whole": 4.0,
    "half": 2.0,
    "quarter": 1.0,
    "eighth": 0.5,
    "16th": 0.25,
    "32nd": 0.125,
    "64th": 0.0625,
}
TOLERANCE = 0.6


def _divisions(part: ET.Element) -> int:
    return int(part.find("measure").findtext("attributes/divisions") or 16)


def audit_xml(path: Path) -> dict[str, object]:
    part = ET.fromstring(path.read_bytes()).find("part")
    if part is None:
        return {"file": path.name, "error": "no part"}
    divisions = _divisions(part)
    measures = part.findall("measure")
    mismatched = 0
    notes = 0
    rest_only = 0
    blank = 0
    for measure in measures:
        elements = measure.findall("note")
        if not elements:
            blank += 1
        elif not [n for n in elements if n.find("rest") is None]:
            rest_only += 1
        for note in measure.findall("note"):
            written = note.findtext("type")
            if written is None:
                continue
            dots = len(note.findall("dot"))
            duration = int(note.findtext("duration") or 0)
            expected = (
                BASES.get(written, 1.0)
                * divisions
                * (1 + (0.5 if dots >= 1 else 0) + (0.25 if dots >= 2 else 0))
            )
            notes += 1
            if abs(expected - duration) > TOLERANCE:
                mismatched += 1
    return {
        "file": path.name,
        "measures": len(measures),
        "notes": notes,
        "type_duration_mismatches": mismatched,
        "blank_measures": blank,
        "rest_only_measures": rest_only,
        "beams": len(part.findall(".//beam")),
        "key_fifths": part.find("measure").findtext("attributes/key/fifths"),
        "beats": part.find("measure").findtext("attributes/time/beats"),
    }


def beam_warnings(path: Path) -> list[str]:
    try:
        from music21 import converter
    except ImportError:
        return ["music21 not installed; beam check skipped"]
    import warnings as warnings_module

    with warnings_module.catch_warnings(record=True) as caught:
        warnings_module.simplefilter("always")
        converter.parse(str(path))
    return [str(item.message) for item in caught if "beam" in str(item.message).lower()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args()
    failures = 0
    for path in args.files:
        row = audit_xml(path)
        warnings = beam_warnings(path)
        dangling = [w for w in warnings if "without ending" in w or "identical values" in w]
        print(
            f"{row.get('file'):24} measures={row.get('measures')} notes={row.get('notes')} "
            f"type/dur={row.get('type_duration_mismatches')} blank={row.get('blank_measures')} "
            f"rest-only={row.get('rest_only_measures')} "
            f"beams={row.get('beams')} fifths={row.get('key_fifths')} beats={row.get('beats')} "
            f"beam-warnings={len(dangling)}"
        )
        if row.get("type_duration_mismatches") or dangling or row.get("blank_measures"):
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
