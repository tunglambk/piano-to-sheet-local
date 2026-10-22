"""S8 render helpers: Verovio pages, MEI and score MIDI."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Rendered:
    mei: str
    pages: list[str]
    midi_b64: str
    verovio_version: str


def render(musicxml: bytes, scale: int = 40, page_width: int = 2100) -> Rendered:
    import verovio

    toolkit = verovio.toolkit()  # type: ignore[attr-defined]
    toolkit.resetXmlIdSeed(0)
    toolkit.setOptions(
        {
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
        }
    )
    if not toolkit.loadData(musicxml.decode("utf-8")):
        raise ValueError("Verovio could not parse the MusicXML")
    pages = [toolkit.renderToSVG(page) for page in range(1, toolkit.getPageCount() + 1)]
    return Rendered(
        mei=toolkit.getMEI(),
        pages=pages,
        midi_b64=toolkit.renderToMIDI(),
        verovio_version=str(toolkit.getVersion()),
    )
