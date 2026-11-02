"""S6 — post-processing and XML normalisation.

Phase 1 keeps this stage conservative: it normalises the document so runs are
byte-deterministic (R-07), guarantees the two-staff scaffolding exists, and
reports per-measure duration problems as warnings. Musical rules that need real
listening (spelling refinements, clef/ottava choices, dynamic marks) land in P4;
the interface and the checks are here.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

from p2s import __version__
from p2s.core.schemas import ScoreDoc
from p2s.post.align import parse_score_notes
from p2s.render.score_writer import WriterNote, write_score


def _text(el: ET.Element, path: str, default: str | None = None) -> str | None:
    found = el.find(path)
    return found.text if found is not None else default


def _to_int(value: str | None, default: int = 0) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _measure_durations(measure: ET.Element) -> dict[int, int]:
    """Total ticks per staff in a measure, honouring <backup>/<forward>."""
    totals: dict[int, int] = {}
    position = 0
    staff = 1
    for child in measure:
        if child.tag == "backup":
            position -= _to_int(_text(child, "duration"))
        elif child.tag == "forward":
            position += _to_int(_text(child, "duration"))
        elif child.tag == "note":
            staff = _to_int(_text(child, "staff"), staff)
            duration = _to_int(_text(child, "duration"))
            totals[staff] = max(totals.get(staff, 0), position + duration)
            if child.find("chord") is None:
                position += duration
                totals[staff] = max(totals.get(staff, 0), position)
    return totals


def _sanitize_measure(measure: ET.Element, bar_ticks: int) -> list[str]:
    """Make a measure safe for strict importers (MuseScore aborts on overflow).

    M2ST sometimes emits a voice longer than the bar, or a backup larger than the
    position it returns to. Truncate notes/backups/forwards so every position
    stays inside [0, bar_ticks].
    """
    issues: list[str] = []
    position = 0
    for child in list(measure):
        if child.tag == "backup":
            duration_el = child.find("duration")
            duration = _to_int(duration_el.text if duration_el is not None else None)
            if duration > position:
                issues.append(f"backup {duration} > position {position}")
                if duration_el is not None:
                    duration_el.text = str(position)
                duration = position
            position -= duration
        elif child.tag == "forward":
            duration_el = child.find("duration")
            duration = _to_int(duration_el.text if duration_el is not None else None)
            if position + duration > bar_ticks:
                issues.append(f"forward past the bar ({position}+{duration}>{bar_ticks})")
                duration = max(0, bar_ticks - position)
                if duration_el is not None:
                    duration_el.text = str(duration)
            position += duration
        elif child.tag == "note":
            duration_el = child.find("duration")
            duration = _to_int(duration_el.text if duration_el is not None else None)
            if child.find("chord") is None:
                if position + duration > bar_ticks:
                    issues.append(f"note past the bar ({position}+{duration}>{bar_ticks})")
                    duration = max(0, bar_ticks - position)
                    if duration_el is not None:
                        duration_el.text = str(duration)
                position += duration
                if duration == 0:
                    measure.remove(child)
                    issues.append("zero-length note dropped")
    return issues


def _linearize_measure(measure: ET.Element, bar_ticks: int) -> bool:
    """Flatten multi-voice measures into one voice without <backup>.

    MuseScore 4 rejects some M2ST scores whose <backup> durations do not line up
    with the notes. Re-emitting the same notes in document order, separated by
    <forward>, keeps note types, dots, beams, tuplets and accidentals while
    removing the construct that breaks the import.
    """
    backups = measure.findall("backup")
    if not backups:
        return False
    position = 0
    events: list[tuple[int, ET.Element]] = []
    kept: list[ET.Element] = []
    for child in list(measure):
        if child.tag == "backup" or child.tag == "forward" or child.tag == "note":
            continue
        kept.append(child)
    for child in list(measure):
        if child.tag == "backup":
            position = max(0, position - _to_int(child.findtext("duration")))
        elif child.tag == "forward":
            position += _to_int(child.findtext("duration"))
        elif child.tag == "note":
            duration = _to_int(child.findtext("duration"))
            chord = child.find("chord") is not None
            copied = ET.fromstring(ET.tostring(child))
            if chord:
                if not events:
                    continue
                events.append((events[-1][0], copied))
                continue
            events.append((position, copied))
            position += duration
    # Rebuild: keep attributes/directions, then the linearised notes.
    for child in list(measure):
        measure.remove(child)
    for child in kept:
        measure.append(child)
    cursor = 0
    events.sort(key=lambda item: item[0])
    for start, element in events:
        if start > cursor:
            forward = ET.SubElement(measure, "forward")
            ET.SubElement(forward, "duration").text = str(start - cursor)
            cursor = start
        elif start < cursor:
            # Overlapping voices: drop the overlap by shortening the note.
            duration = _to_int(element.findtext("duration"))
            new_duration = max(0, duration - (cursor - start))
            if new_duration <= 0:
                continue
            duration_el = element.find("duration")
            if duration_el is not None:
                duration_el.text = str(new_duration)
        measure.append(element)
    return True


def _needs_reengrave(root: ET.Element) -> bool:
    """Strict importers choke on M2ST's many-voice measures; re-engrave those."""
    for part in root.findall("part"):
        for measure in part.findall("measure"):
            voices = {
                (n.findtext("staff") or "1", n.findtext("voice") or "1") for n in measure.findall("note")
            }
            if len(voices) > 2:
                return True
    return False


def _reengrave(root: ET.Element) -> bytes:
    musicxml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    parsed = parse_score_notes(musicxml)
    parts = root.findall("part")
    first_attrs = parts[0].find("measure/attributes") if parts else None
    divisions = _to_int(first_attrs.findtext("divisions") if first_attrs is not None else None, 16)
    fifths = _to_int(first_attrs.findtext("key/fifths") if first_attrs is not None else None, 0)
    mode = first_attrs.findtext("key/mode") if first_attrs is not None else "major"
    meters: list[tuple[int, int]] = []
    beats, beat_type = 4, 4
    for measure in parts[0].findall("measure") if parts else []:
        time_el = measure.find("attributes/time")
        if time_el is not None:
            beats = _to_int(time_el.findtext("beats"), beats)
            beat_type = _to_int(time_el.findtext("beat-type"), beat_type)
        meters.append((beats, beat_type))
    notes = [
        WriterNote(
            pitch=note.pitch,
            start_tick=int(round(note.beat * divisions)),
            end_tick=int(round((note.beat + note.duration_beats) * divisions)),
            staff=note.staff,
            note_id=note.note_id,
            step=note.step,
            alter=note.alter,
            octave=note.octave,
        )
        for note in parsed
    ]
    if not notes:
        return musicxml
    return write_score(
        notes,
        divisions=divisions,
        meters=meters or [(4, 4)],
        fifths=fifths,
        mode=mode or "major",
        n_measures=len(meters),
    )


def _apply_tempo(root: ET.Element, bpm: float | None) -> None:
    """Write a metronome mark in the first measure (D-094).

    A score without a tempo mark tells the player nothing about speed, and the beat
    grid already knows it: the median beat period is the tempo the transcription
    assumed.
    """
    if not bpm or bpm <= 0:
        return
    part = root.find("part")
    if part is None:
        return
    measure = part.find("measure")
    if measure is None:
        return
    for existing in measure.findall("direction"):
        if existing.find("direction-type/metronome") is not None:
            return
    direction = ET.Element("direction", placement="above")
    direction_type = ET.SubElement(direction, "direction-type")
    metronome = ET.SubElement(direction_type, "metronome")
    ET.SubElement(metronome, "beat-unit").text = "quarter"
    ET.SubElement(metronome, "per-minute").text = str(int(round(bpm)))
    ET.SubElement(direction, "sound", tempo=str(round(float(bpm), 2)))
    # After <attributes>, before the first note.
    position = 1 if measure.find("attributes") is not None else 0
    measure.insert(position, direction)


def _apply_metadata(root: ET.Element, title: str | None, composer: str | None) -> None:
    """Work title and composer, which the engraver prints above the staff (D-093).

    Applied to the final document: a re-engrave step rebuilds the XML from notes and
    would drop the header otherwise.
    """
    # A score without a title prints as a bare page of notes; the work title and the
    # composer come from the job metadata (D-093).
    if title:
        work = root.find("work")
        if work is None:
            work = ET.Element("work")
            root.insert(0, work)
        for existing in work.findall("work-title"):
            work.remove(existing)
        ET.SubElement(work, "work-title").text = title
    if title or composer:
        movement = root.find("movement-title")
        if movement is None and title:
            movement = ET.Element("movement-title")
            movement.text = title
            root.insert(1, movement)
    identification = root.find("identification")
    if identification is None:
        identification = ET.SubElement(root, "identification")
    for existing in identification.findall("creator"):
        identification.remove(existing)
    if composer:
        creator = ET.Element("creator", type="composer")
        creator.text = composer
        identification.insert(0, creator)


def postprocess(
    doc: ScoreDoc,
    *,
    time_signature: str | None = None,
    title: str | None = None,
    composer: str | None = None,
) -> ScoreDoc:
    root = ET.fromstring(doc.musicxml)
    warnings = list(doc.warnings)

    # Deterministic identification block: drop dates, pin software.
    identification = root.find("identification")
    if identification is not None:
        root.remove(identification)
    identification = ET.Element("identification")
    position = 2 if (title or composer) else 0
    root.insert(min(position, len(root)), identification)
    ET.SubElement(identification, "encoding")
    ET.SubElement(identification, "software").text = f"p2s {__version__}"

    part = root.find("part")
    if part is None:
        warnings.append("score has no part element")
        return ScoreDoc(
            musicxml=ET.tostring(root, encoding="utf-8", xml_declaration=True),
            alignment=doc.alignment,
            key=doc.key,
            warnings=warnings,
        )

    first_measure = part.find("measure")
    if first_measure is not None:
        attributes = first_measure.find("attributes")
        if attributes is None:
            attributes = ET.Element("attributes")
            first_measure.insert(0, attributes)
        if attributes.find("divisions") is None:
            ET.SubElement(attributes, "divisions").text = "16"
        if attributes.find("staves") is None:
            ET.SubElement(attributes, "staves").text = "2"
        if attributes.find("time") is None and time_signature:
            beats, beat_type = time_signature.split("/")
            time_el = ET.SubElement(attributes, "time")
            ET.SubElement(time_el, "beats").text = beats
            ET.SubElement(time_el, "beat-type").text = beat_type
        structural_issues = False
        divisions = _to_int(_text(attributes, "divisions"), 16)
        beats = _to_int(_text(attributes, "time/beats") if attributes.find("time") is not None else None, 4)
        beat_type = _to_int(
            _text(attributes, "time/beat-type") if attributes.find("time") is not None else None, 4
        )
        for measure in part.findall("measure"):
            number = measure.get("number", "?")
            measure_attrs = measure.find("attributes")
            if measure_attrs is not None:
                if measure_attrs.find("divisions") is not None:
                    divisions = _to_int(_text(measure_attrs, "divisions"), divisions)
                if measure_attrs.find("time") is not None:
                    beats = _to_int(_text(measure_attrs, "time/beats"), beats)
                    beat_type = _to_int(_text(measure_attrs, "time/beat-type"), beat_type)
            bar_ticks = int(divisions * beats * 4 / max(1, beat_type))
            issues = _sanitize_measure(measure, bar_ticks)
            for issue in issues:
                warnings.append(f"measure {number}: {issue}")
            if issues:
                structural_issues = True
            totals = _measure_durations(measure)
            for staff, total in sorted(totals.items()):
                if total != bar_ticks and total != 0:
                    warnings.append(
                        f"measure {number} staff {staff}: duration {total} ticks, expected {bar_ticks}"
                    )
                    structural_issues = True
    else:
        warnings.append("score has no measures")

    if structural_issues or _needs_reengrave(root):
        warnings.append("score re-engraved to a single voice per staff (strict-import normalisation)")
        root = ET.fromstring(_reengrave(root))
        identification = ET.SubElement(root, "identification")
        ET.SubElement(identification, "encoding")
        ET.SubElement(identification, "software").text = f"p2s {__version__}"

    _apply_metadata(root, title, composer)
    ET.indent(root)
    return ScoreDoc(
        musicxml=ET.tostring(root, encoding="utf-8", xml_declaration=True),
        alignment=doc.alignment,
        key=doc.key,
        warnings=warnings,
    )
