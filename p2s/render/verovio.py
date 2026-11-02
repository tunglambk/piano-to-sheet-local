"""S8 render helpers: Verovio pages, MEI and score MIDI.

Verovio is a C++ library with Python bindings: a malformed score does not raise an
exception, it **segfaults the interpreter**. Any notation we cannot prove safe must
therefore be rendered out of process, or a single bad chord kills the whole job
(D-092). The renderer below runs Verovio in a child process and degrades to "no SVG
pages" with a warning when that child dies; the PDF still comes from MuseScore.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_CHILD = r"""
import json, sys
import verovio

musicxml_path, out_path, scale, page_width = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
toolkit = verovio.toolkit()
toolkit.resetXmlIdSeed(0)
toolkit.setOptions({
    "scale": scale,
    "pageWidth": page_width,
    "pageHeight": 2970,
    "adjustPageHeight": True,
    "adjustPageWidth": False,
    "breaks": "auto",
    "footer": "none",
    "header": "none",
    "xmlIdChecksum": True,
    "svgViewBox": True,
})
if not toolkit.loadData(open(musicxml_path, encoding="utf-8").read()):
    print(json.dumps({"error": "parse"}))
    raise SystemExit(3)
pages = [toolkit.renderToSVG(page) for page in range(1, toolkit.getPageCount() + 1)]
print(json.dumps({
    "pages": pages,
    "mei": toolkit.getMEI(),
    "midi": toolkit.renderToMIDI(),
    "version": str(toolkit.getVersion()),
}))
"""


@dataclass
class Rendered:
    mei: str
    pages: list[str]
    midi_b64: str
    verovio_version: str


def render(musicxml: bytes, scale: int = 40, page_width: int = 2100, timeout_s: float = 120.0) -> Rendered:
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "score.musicxml"
        src.write_bytes(musicxml)
        try:
            proc = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    _CHILD,
                    str(src),
                    str(Path(tmp) / "out.json"),
                    str(scale),
                    str(page_width),
                ],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ValueError("Verovio timed out") from exc
    if proc.returncode != 0 or not proc.stdout.strip():
        # A segfault (negative return code) or a parse failure: no pages this run.
        reason = "crashed" if proc.returncode < 0 else "failed"
        raise ValueError(f"Verovio {reason} on this score (return code {proc.returncode})")
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    if "error" in payload:
        raise ValueError("Verovio could not parse the MusicXML")
    return Rendered(
        mei=payload["mei"],
        pages=payload["pages"],
        midi_b64=payload["midi"],
        verovio_version=payload["version"],
    )
