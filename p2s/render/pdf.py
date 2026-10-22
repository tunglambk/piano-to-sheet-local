"""PDF export: MuseScore 4 CLI first, Verovio SVG + cairosvg as the fallback (D-024)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from p2s.core.config import REPO_ROOT

MUSESCORE_CANDIDATES = [
    os.environ.get("P2S_MUSESCORE", ""),
    str(REPO_ROOT / ".tools" / "mscore" / "AppRun"),
    shutil.which("mscore") or "",
    shutil.which("musescore") or "",
]


def find_musescore() -> Path | None:
    for candidate in MUSESCORE_CANDIDATES:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    return None


class PdfResult:
    def __init__(self, path: Path, engine: str, warnings: list[str]) -> None:
        self.path = path
        self.engine = engine
        self.warnings = warnings


def render_pdf(
    musicxml: bytes, out_pdf: Path, svg_pages: list[str] | None = None, timeout_s: float = 180.0
) -> PdfResult:
    warnings: list[str] = []
    musescore = find_musescore()
    if musescore is not None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "score.musicxml"
            src.write_bytes(musicxml)
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
            try:
                proc = subprocess.run(
                    [str(musescore), "-o", str(out_pdf), str(src)],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    env=env,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                proc = None
                warnings.append("MuseScore timed out; falling back to SVG → PDF")
            if proc is not None and proc.returncode == 0 and out_pdf.exists() and out_pdf.stat().st_size > 0:
                return PdfResult(out_pdf, "musescore", warnings)
            warnings.append(
                f"MuseScore failed ({(proc.stderr if proc else 'timeout').strip()[:200]}); using SVG → PDF"
            )
    else:
        warnings.append("MuseScore not found; using SVG → PDF")
    if not svg_pages:
        raise RuntimeError("no SVG pages to convert and MuseScore is unavailable")
    _svg_to_pdf(svg_pages, out_pdf)
    return PdfResult(out_pdf, "verovio+cairosvg", warnings)


def _svg_to_pdf(svg_pages: list[str], out_pdf: Path) -> None:
    import cairosvg
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    for svg in svg_pages:
        data = cairosvg.svg2pdf(bytestring=svg.encode("utf-8"))
        reader = PdfReader(__import__("io").BytesIO(data))
        for page in reader.pages:
            writer.add_page(page)
    with open(out_pdf, "wb") as fh:
        writer.write(fh)
