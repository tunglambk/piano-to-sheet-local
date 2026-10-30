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


def musescore_invocation(source: Path, out: Path) -> tuple[list[str], dict[str, str]] | None:
    """Command and environment to run MuseScore headlessly (D-086).

    Returns None when no MuseScore binary is present. Shared with the benchmark
    baseline so both use the same flags: `-f` is required (the 4.x CLI exits 40
    without it), the unpacked library directory is added to LD_LIBRARY_PATH and
    Xvfb provides the display the Qt build insists on.
    """
    musescore = find_musescore()
    if musescore is None:
        return None
    command = [str(musescore), "-f", "-o", str(out), str(source)]
    env = dict(os.environ)
    extra_lib = REPO_ROOT / ".tools" / "mscore-libs"
    if extra_lib.exists():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{extra_lib}:{existing}" if existing else str(extra_lib)
    xvfb = shutil.which("xvfb-run")
    if xvfb:
        command = [xvfb, "-a", *command]
    else:
        env["QT_QPA_PLATFORM"] = "offscreen"
    return command, env


def render_pdf(
    musicxml: bytes, out_pdf: Path, svg_pages: list[str] | None = None, timeout_s: float = 180.0
) -> PdfResult:
    warnings: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "score.musicxml"
        src.write_bytes(musicxml)
        invocation = musescore_invocation(src, out_pdf)
        if invocation is not None:
            command, env = invocation
            try:
                proc = subprocess.run(
                    command,
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
