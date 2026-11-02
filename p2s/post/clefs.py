"""Clef changes inside a piece, chosen to keep notes on the staff (D-112).

A single clef per staff cannot follow music that moves by two octaves: measurements
on ten dev items showed **23.1 %** of the notes needing more than three ledger lines,
and an analysis of the best clef *per measure* showed that figure could fall to
**6.2 %**. This module inserts clef changes where they pay for themselves, with a
penalty for every change so the score does not flip back and forth.
"""

from __future__ import annotations

from xml.etree import ElementTree as ET

# Staff lines without ledger lines: treble E4..F5 (64..77), bass G2..A3 (43..57).
STAFF_RANGE = {"G": (64, 77), "F": (43, 57)}
MARGIN = 6  # three ledger lines, two semitones apart
CANDIDATES: list[tuple[str, str, int]] = [
    ("G", "2", 0),
    ("G", "2", 1),
    ("G", "2", -1),
    ("F", "4", 0),
    ("F", "4", -1),
    ("F", "4", 1),
]
SWITCH_PENALTY = 3  # in "notes left far off the staff"


def _pitch(note: ET.Element) -> int | None:
    pitch = note.find("pitch")
    if pitch is None:
        return None
    step = pitch.findtext("step") or "C"
    octave = pitch.findtext("octave") or "4"
    alter = pitch.findtext("alter") or "0"
    try:
        return (
            12 * (int(octave) + 1)
            + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[step]
            + int(float(alter))
        )
    except (KeyError, ValueError):
        return None


def _far_count(pitches: list[int], sign: str, line: str, octave_change: int) -> int:
    low, high = STAFF_RANGE[sign]
    shift = 12 * octave_change
    return sum(1 for value in pitches if (value - shift) > high + MARGIN or (value - shift) < low - MARGIN)


def _insert_clef(measure: ET.Element, staff: int, sign: str, line: str, octave_change: int) -> None:
    attributes = measure.find("attributes")
    if attributes is None:
        attributes = ET.Element("attributes")
        measure.insert(0, attributes)
    for existing in attributes.findall("clef"):
        if existing.get("number") == str(staff):
            attributes.remove(existing)
    clef = ET.Element("clef", number=str(staff))
    ET.SubElement(clef, "sign").text = sign
    ET.SubElement(clef, "line").text = line
    if octave_change:
        # MusicXML spells it `clef-octave-change`; the shorter name is ignored and
        # every note would be drawn an octave away from where it sounds (D-112).
        ET.SubElement(clef, "clef-octave-change").text = str(octave_change)
    attributes.append(clef)


def apply_clef_changes(root: ET.Element, penalty: int = SWITCH_PENALTY) -> int:
    """Insert clef changes per staff; return how many were written.

    A dynamic program picks the clef sequence that minimises
    `sum(notes left far off the staff) + penalty × changes`, per staff.
    """
    part = root.find("part")
    if part is None:
        return 0
    measures = part.findall("measure")
    if len(measures) < 2:
        return 0
    written = 0
    for staff in (1, 2):
        pitches_per_measure: list[list[int]] = []
        for measure in measures:
            values = []
            for note in measure.findall("note"):
                if (note.findtext("staff") or "1") != str(staff):
                    continue
                value = _pitch(note)
                if value is not None:
                    values.append(value)
            pitches_per_measure.append(values)
        if not any(pitches_per_measure):
            continue
        cost = [
            [_far_count(values, *candidate) for candidate in CANDIDATES] for values in pitches_per_measure
        ]
        # dp[i][c] = best cost up to measure i with clef c active at measure i.
        dp: list[list[int]] = [[0] * len(CANDIDATES) for _ in pitches_per_measure]
        back: list[list[int]] = [[0] * len(CANDIDATES) for _ in pitches_per_measure]
        for index, row in enumerate(cost):
            for candidate, value in enumerate(row):
                if index == 0:
                    dp[index][candidate] = value
                    back[index][candidate] = candidate
                    continue
                best_previous = min(
                    range(len(CANDIDATES)),
                    key=lambda prev: dp[index - 1][prev] + (penalty if prev != candidate else 0),
                )
                dp[index][candidate] = (
                    dp[index - 1][best_previous] + (penalty if best_previous != candidate else 0) + value
                )
                back[index][candidate] = best_previous
        final = min(range(len(CANDIDATES)), key=lambda candidate: dp[-1][candidate])
        sequence = [final]
        for index in range(len(cost) - 1, 0, -1):
            sequence.append(back[index][sequence[-1]])
        sequence.reverse()
        active: tuple[str, str, int] | None = None
        for measure, candidate in zip(measures, sequence, strict=False):
            chosen = CANDIDATES[candidate]
            if chosen == active:
                continue
            sign, line, octave_change = chosen
            _insert_clef(measure, staff, sign, line, octave_change)
            active = chosen
            written += 1
    return written
