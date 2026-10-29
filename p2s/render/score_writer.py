"""Deterministic two-staff MusicXML writer (S5 fallback and the S6 re-engraver).

Textbook-clean output: one voice per staff, rests filled, ties split at barlines,
note ids `n{staff}-{measure}-{index}` (continuations get `-t2`, `-t3`). Supporting
per-measure time signatures lets S6 re-engrave scores whose bar lengths change.
"""

from __future__ import annotations

from dataclasses import dataclass
from xml.etree import ElementTree as ET

SHARP_SPELLINGS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_SPELLINGS = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
NOTE_TYPES = [
    (4.0, "whole"),
    (3.0, "half"),
    (2.0, "half"),
    (1.5, "quarter"),
    (1.0, "quarter"),
    (0.75, "eighth"),
    (0.5, "eighth"),
    (0.25, "16th"),
    (0.125, "32nd"),
]


@dataclass
class WriterNote:
    pitch: int
    start_tick: int
    end_tick: int
    staff: int
    note_id: str
    step: str | None = None
    alter: int = 0
    octave: int | None = None


def spell(pitch: int, fifths: int) -> tuple[str, int, int]:
    name = (FLAT_SPELLINGS if fifths < 0 else SHARP_SPELLINGS)[pitch % 12]
    alter = len(name) - 1 if name.endswith("#") else (0 if len(name) == 1 else -1)
    return name[0], alter, pitch // 12 - 1


NOTE_BASES: list[tuple[float, str]] = [
    (4.0, "whole"),
    (2.0, "half"),
    (1.0, "quarter"),
    (0.5, "eighth"),
    (0.25, "16th"),
    (0.125, "32nd"),
    (0.0625, "64th"),
]


def _note_type(duration: int, divisions: int) -> tuple[str, int]:
    """Return the written type and how many dots it needs (D-053).

    A duration that was not an exact table value used to be labelled "quarter",
    which made the file internally inconsistent: `<duration>6</duration>` with
    `<type>quarter</type>` at 16 divisions per quarter. The type is now the closest
    base value with up to two dots, so type + dots always add up to the duration.
    """
    ratio = duration / max(1, divisions)
    candidates: list[tuple[float, str, int]] = []
    for value, name in NOTE_BASES:
        candidates.append((value, name, 0))
        candidates.append((value * 1.5, name, 1))
        candidates.append((value * 1.75, name, 2))
    best = min(candidates, key=lambda item: abs(item[0] - ratio))
    return best[1], best[2]


def _representable_ticks(divisions: int) -> list[int]:
    """Every duration that can be written as a note value with up to two dots."""
    values = {
        int(round(base * divisions * factor)) for base, _name in NOTE_BASES for factor in (1.0, 1.5, 1.75)
    }
    return sorted(v for v in values if v > 0)


def _fit_duration(duration: int, available: int, divisions: int) -> int:
    """Largest representable duration that fits (D-054).

    A note clipped to a bar used to end on an arbitrary tick (`5`, `7`, `9`), which
    no note value can express, so the file carried `<duration>` values its own
    `<type>` contradicted. Rounding down to a representable value keeps type, dots
    and duration in agreement.
    """
    if available <= 0:
        return 0
    limit = min(duration, available)
    candidates = [value for value in _representable_ticks(divisions) if value <= limit]
    return max(candidates) if candidates else min(_representable_ticks(divisions))


def _measure_lengths(divisions: int, meters: list[tuple[int, int]], n_measures: int) -> list[int]:
    lengths = []
    for index in range(n_measures):
        beats, beat_type = meters[min(index, len(meters) - 1)] if meters else (4, 4)
        lengths.append(int(divisions * beats * 4 / max(1, beat_type)))
    return lengths


def write_score(
    notes: list[WriterNote],
    *,
    divisions: int,
    meters: list[tuple[int, int]],
    fifths: int,
    mode: str,
    n_measures: int | None = None,
) -> bytes:
    lengths = _measure_lengths(
        divisions, meters, n_measures or max(1, max((n.end_tick for n in notes), default=0))
    )
    while lengths and sum(lengths) < max((n.end_tick for n in notes), default=0):
        lengths.append(lengths[-1] if lengths else divisions * 4)
    n_measures = len(lengths)
    starts = [0]
    for length in lengths:
        starts.append(starts[-1] + length)

    def measure_of(tick: int) -> int:
        for index in range(n_measures):
            if starts[index] <= tick < starts[index + 1]:
                return index
        return n_measures - 1

    root = ET.Element("score-partwise", version="4.0")
    part_list = ET.SubElement(root, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = "Piano"
    part = ET.SubElement(root, "part", id="P1")
    measures = [ET.SubElement(part, "measure", number=str(i + 1)) for i in range(n_measures)]

    attrs = ET.SubElement(measures[0], "attributes")
    ET.SubElement(attrs, "divisions").text = str(divisions)
    key_el = ET.SubElement(attrs, "key")
    ET.SubElement(key_el, "fifths").text = str(fifths)
    ET.SubElement(key_el, "mode").text = mode
    beats, beat_type = meters[0] if meters else (4, 4)
    time_el = ET.SubElement(attrs, "time")
    ET.SubElement(time_el, "beats").text = str(beats)
    ET.SubElement(time_el, "beat-type").text = str(beat_type)
    ET.SubElement(attrs, "staves").text = "2"
    for number, sign, line in ((1, "G", "2"), (2, "F", "4")):
        clef = ET.SubElement(attrs, "clef", number=str(number))
        ET.SubElement(clef, "sign").text = sign
        ET.SubElement(clef, "line").text = line

    # Segments per (staff, measure), ties at barlines, stable ids.
    segments: dict[tuple[int, int], list[tuple[WriterNote, int, int, str | None, str]]] = {}
    for note in sorted(notes, key=lambda n: (n.staff, n.start_tick, n.pitch, n.end_tick)):
        cursor = note.start_tick
        index = 0
        while cursor < note.end_tick:
            m = measure_of(cursor)
            end = min(note.end_tick, starts[m + 1])
            first, last = index == 0, end >= note.end_tick
            tie = (
                None
                if first and last
                else ("both" if not first and not last else ("stop" if not first else "start"))
            )
            note_id = note.note_id if index == 0 else f"{note.note_id}-t{index + 1}"
            segments.setdefault((note.staff, m), []).append(
                (note, cursor - starts[m], end - cursor, tie, note_id)
            )
            cursor = end
            index += 1

    for m in range(n_measures):
        measure = measures[m]
        beats, beat_type = meters[min(m, len(meters) - 1)] if meters else (4, 4)
        if m > 0 and (beats, beat_type) != (meters[min(m - 1, len(meters) - 1)] if meters else (4, 4)):
            change = ET.SubElement(measure, "attributes")
            time_el = ET.SubElement(change, "time")
            ET.SubElement(time_el, "beats").text = str(beats)
            ET.SubElement(time_el, "beat-type").text = str(beat_type)
        for staff in (1, 2):
            if staff == 2:
                backup = ET.SubElement(measure, "backup")
                ET.SubElement(backup, "duration").text = str(lengths[m])
            entries = sorted(segments.get((staff, m), []), key=lambda e: (e[1], e[0].pitch, e[4]))
            cursor = 0
            index = 0
            while index < len(entries):
                note, offset, duration, tie, note_id = entries[index]
                if offset > cursor:
                    _rest(measure, offset - cursor, staff, divisions)
                    cursor = offset
                # Notes sharing an onset are a chord: first normal, the rest with <chord/>.
                group = [entries[index]]
                while index + 1 < len(entries) and entries[index + 1][1] == offset:
                    index += 1
                    group.append(entries[index])
                specs = _beam_specs(
                    entries, divisions, int(divisions * beats * 4 / max(1, beat_type)) // beats
                )
                longest = 0
                for chord_index, (chord_note, _o, chord_duration, chord_tie, chord_id) in enumerate(group):
                    clipped = _fit_duration(chord_duration, lengths[m] - cursor, divisions)
                    if clipped <= 0:
                        continue
                    _note(
                        measure,
                        chord_note,
                        clipped,
                        chord_tie,
                        chord_id,
                        staff,
                        fifths,
                        divisions,
                        chord=chord_index > 0,
                        beams=specs.get(chord_id),
                    )
                    longest = max(longest, clipped)
                cursor += max(longest, 0)
                index += 1
            if cursor < lengths[m]:
                _rest(measure, lengths[m] - cursor, staff, divisions)
        _sanitise_beams(measure)
    ET.indent(root)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _sanitise_beams(measure: ET.Element) -> None:
    """Keep every beam span valid for its staff inside the measure (D-055).

    Beam numbers are per voice, not per measure: staff 1's `begin` must not be
    paired with staff 2's `end`. Grouping by (staff, number) fixes that, and a
    group left with a single note loses its beam, which is what music21 reports as
    "beamspans left without ending".
    """
    per_key: dict[tuple[str, int], list[tuple[ET.Element, ET.Element, str]]] = {}
    for note in measure.findall("note"):
        staff = note.findtext("staff") or "1"
        for beam in note.findall("beam"):
            number = int(beam.get("number", "1"))
            per_key.setdefault((staff, number), []).append((note, beam, (beam.text or "").strip()))
    for beams in per_key.values():
        if len(beams) < 2:
            for note, beam, _state in beams:
                note.remove(beam)
            continue
        states = [state for _note, _beam, state in beams]
        if states[0] == "begin" and "end" not in states:
            beams[-1][1].text = "end"


def _beam_group_ticks(beats: int, beat_type: int, beat_ticks: int) -> int:
    """Beaming unit inside a bar (D-051).

    Simple metres beam per beat; compound metres (6/8, 9/8, 12/8) beam in groups
    of three eighths, which is what a reader expects to see.
    """
    if beat_type == 8 and beats % 3 == 0:
        return 3 * beat_ticks
    return beat_ticks


def _beam_specs(
    entries: list[tuple[WriterNote, int, int, str | None, str]],
    divisions: int,
    beat_ticks: int,
) -> dict[str, list[tuple[int, str]]]:
    """Group eighth-or-shorter notes inside one beat and give each a beam.

    Without beams a run of eighth notes is an unreadable sequence of flagged
    notes; music21 and MuseScore both re-beam on import, but the file is also read
    by tools that do not (D-050).
    """
    groups: dict[int, list[tuple[WriterNote, int, int, str | None, str]]] = {}
    for entry in entries:
        _note, offset, duration = entry[0], entry[1], entry[2]
        if duration > divisions / 2 + 1e-6:
            continue
        groups.setdefault(offset // max(1, beat_ticks), []).append(entry)
    specs: dict[str, list[tuple[int, str]]] = {}
    for members in groups.values():
        if len(members) < 2:
            continue
        for position, (_note, _offset, duration, _tie, note_id) in enumerate(members):
            if position == 0:
                state = "begin"
            elif position == len(members) - 1:
                state = "end"
            else:
                state = "continue"
            levels = 1
            if duration <= divisions / 4 + 1e-6:
                levels = 2
            if duration <= divisions / 8 + 1e-6:
                levels = 3
            specs[note_id] = [(level, state) for level in range(1, levels + 1)]
    return specs


def _note(
    measure: ET.Element,
    note: WriterNote,
    duration: int,
    tie: str | None,
    note_id: str,
    staff: int,
    fifths: int,
    divisions: int,
    chord: bool = False,
    beams: list[tuple[int, str]] | None = None,
) -> None:
    if note.step is not None and note.octave is not None:
        step, alter, octave = note.step, note.alter, note.octave
    else:
        step, alter, octave = spell(note.pitch, fifths)
    el = ET.SubElement(measure, "note", id=note_id)
    pitch_el = ET.SubElement(el, "pitch")
    ET.SubElement(pitch_el, "step").text = step
    if alter:
        ET.SubElement(pitch_el, "alter").text = str(alter)
    ET.SubElement(pitch_el, "octave").text = str(octave)
    ET.SubElement(el, "duration").text = str(duration)
    if tie in ("start", "both"):
        ET.SubElement(el, "tie", type="start")
    if tie in ("stop", "both"):
        ET.SubElement(el, "tie", type="stop")
    ET.SubElement(el, "voice").text = "1"
    type_name, dots = _note_type(duration, divisions)
    ET.SubElement(el, "type").text = type_name
    for _ in range(dots):
        ET.SubElement(el, "dot")
    if beams and not chord:
        for number, state in beams:
            ET.SubElement(el, "beam", number=str(number)).text = state
    if tie:
        notations = ET.SubElement(el, "notations")
        if tie in ("start", "both"):
            ET.SubElement(notations, "tied", type="start")
        if tie in ("stop", "both"):
            ET.SubElement(notations, "tied", type="stop")
    ET.SubElement(el, "staff").text = str(staff)


def _rest(measure: ET.Element, duration: int, staff: int, divisions: int) -> None:
    """Fill a gap with one or more rests of written values (D-054).

    A single rest of, say, 5 ticks has no note value either, so the gap is split
    into representable chunks instead of one impossible duration.
    """
    remaining = duration
    while remaining > 0:
        chunk = _fit_duration(remaining, remaining, divisions)
        if chunk <= 0:
            break
        _rest_chunk(measure, chunk, staff, divisions)
        remaining -= chunk


def _rest_chunk(measure: ET.Element, duration: int, staff: int, divisions: int) -> None:
    el = ET.SubElement(measure, "note")
    ET.SubElement(el, "rest")
    ET.SubElement(el, "duration").text = str(duration)
    ET.SubElement(el, "voice").text = "1"
    type_name, dots = _note_type(duration, divisions)
    ET.SubElement(el, "type").text = type_name
    for _ in range(dots):
        ET.SubElement(el, "dot")
    ET.SubElement(el, "staff").text = str(staff)
