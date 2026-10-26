"""Rule-based quantiser (S5 fallback and the `fast` preset). CPU only, deterministic.

Pipeline: beats → tick map → onset/duration quantisation → hand split → key and
meter → two-staff MusicXML with deterministic note ids (`n{staff}-{measure}-{i}`).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import numpy as np

from p2s.core.config import EngineSpec, ModelLockEntry
from p2s.core.schemas import BeatGrid, EngineInfo, Performance, ScoreDoc, ScoreOptions
from p2s.engines.base import EngineBase

KRUMHANSL_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KRUMHANSL_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
SEMITONES = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
MAJOR_FIFTHS = {0: 0, 1: 7, 2: 2, 3: 9, 4: 4, 5: 11, 6: 6, 7: 1, 8: 8, 9: 3, 10: 10, 11: 5}
MINOR_FIFTHS = {0: 3, 1: 10, 2: 5, 3: 0, 4: 7, 5: 2, 6: 9, 7: 4, 8: 11, 9: 6, 10: 1, 11: 8}
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
class QuantizedNote:
    pitch: int
    start_tick: int
    end_tick: int
    velocity: int
    staff: int = 1
    measure: int = 0
    index: int = 0
    segments: list[tuple[int, int, int, str | None, str]] = field(default_factory=list)


def _spell(pitch: int, fifths: int) -> tuple[str, int, int]:
    name = (FLAT_SPELLINGS if fifths < 0 else SHARP_SPELLINGS)[pitch % 12]
    return name[0], (len(name) - 1) * (1 if name[1:] == "#" else -1), pitch // 12 - 1


def _estimate_key(perf: Performance, hint: str | None) -> tuple[int, str, str]:
    if hint:
        text = hint.strip()
        mode = "minor" if text.lower().endswith("m") or "minor" in text.lower() else "major"
        tonic = text[:1].upper()
        pc = SEMITONES.get(tonic, 0)
        fifths = (MINOR_FIFTHS if mode == "minor" else MAJOR_FIFTHS)[pc]
        return fifths, mode, f"{tonic} {mode}"
    histogram = np.zeros(12, dtype=float)
    for note in perf.notes:
        histogram[note.pitch % 12] += max(1e-3, note.offset - note.onset)
    if histogram.sum() <= 0:
        return 0, "major", "C major"
    best = (-1e9, 0, "major")
    for pc in range(12):
        rotated = np.roll(histogram, -pc)
        major = float(np.dot(rotated, KRUMHANSL_MAJOR))
        minor = float(np.dot(rotated, KRUMHANSL_MINOR))
        if major > best[0]:
            best = (major, pc, "major")
        if minor > best[0]:
            best = (minor, pc, "minor")
    _, pc, mode = best
    fifths = (MINOR_FIFTHS if mode == "minor" else MAJOR_FIFTHS)[pc]
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return fifths, mode, f"{names[pc]} {mode}"


class RuleQuantizer(EngineBase):
    def __init__(self, spec: EngineSpec, lock: ModelLockEntry, device: str = "cpu") -> None:
        super().__init__("rule_quant", spec, lock, "cpu")

    def _load(self) -> None:
        return None

    def _version(self) -> str:
        from p2s import __version__

        return f"rulequant-{__version__}"

    def _weights(self) -> dict[str, str]:
        return {}

    def info(self) -> EngineInfo:
        base = super().info()
        return base.model_copy(update={"id": "rule_quant", "version": self._version(), "device": "cpu"})

    # ------------------------------------------------------------------ build
    def build(self, perf: Performance, grid: BeatGrid, opts: ScoreOptions) -> ScoreDoc:
        warnings: list[str] = []
        if not perf.notes:
            return self._empty_score(["performance has no notes"], opts)
        sub = {"1/8": 2, "1/16": 4, "1/32": 8}[opts.quantize_grid]
        divisions = 4 * sub
        beats = sorted(grid.beats)
        if len(beats) < 2:
            warnings.append("no usable beat grid; assumed 120 BPM from the first onset")
            t0 = perf.notes[0].onset
            span = max(n.offset for n in perf.notes) - t0
            beats = [t0 + i * 0.5 for i in range(int(span / 0.5) + 3)]
        beats_per_bar = 4
        # The downbeats decide both the bar length and where the first bar starts:
        # taking the meter from the time signature alone put bar lines on the wrong
        # beat whenever the piece starts on an anacrusis (D-035).
        phase_beats = 0
        indices: list[int] = []
        if len(grid.downbeats) >= 3:
            for downbeat in grid.downbeats:
                nearest = min(range(len(beats)), key=lambda i: abs(beats[i] - downbeat))
                indices.append(nearest)
            gaps = [b - a for a, b in zip(indices, indices[1:], strict=False) if 1 <= b - a <= 12]
            if gaps:
                gaps.sort()
                candidate = int(round(statistics.median(gaps)))
                if candidate >= 2:
                    beats_per_bar = candidate
                    phase_beats = indices[0] % beats_per_bar
        if grid.time_signatures:
            try:
                beats_per_bar = int(grid.time_signatures[0][1].split("/")[0])
            except (ValueError, IndexError):
                warnings.append(f"cannot parse time signature {grid.time_signatures[0][1]!r}; assumed 4/4")
            # The phase was derived for the downbeat-implied bar length; once the
            # time signature overrides the length it has to be recomputed, or every
            # bar line shifts by the difference (found while measuring D-045).
            if indices:
                phase_beats = indices[0] % max(2, beats_per_bar)
        if opts.time_signature_hint:
            try:
                beats_per_bar = int(opts.time_signature_hint.split("/")[0])
            except ValueError:
                warnings.append(f"cannot parse time-signature hint {opts.time_signature_hint!r}")

        def beat_pos(t: float) -> float:
            if t <= beats[0]:
                return (t - beats[0]) / (beats[1] - beats[0])
            for i in range(len(beats) - 1):
                if beats[i] <= t < beats[i + 1]:
                    return i + (t - beats[i]) / (beats[i + 1] - beats[i])
            span = beats[-1] - beats[-2]
            return (len(beats) - 1) + (t - beats[-1]) / span

        step = divisions / sub

        def snap(t: float) -> int:
            tick = int(round(beat_pos(t) * divisions / step) * step) - phase_beats * divisions
            return max(0, tick)

        notes: list[QuantizedNote] = []
        for note in perf.notes:
            start = max(0, snap(note.onset))
            end = snap(note.offset)
            if end <= start:
                end = start + int(step)
            notes.append(QuantizedNote(note.pitch, start, end, note.velocity))
        self._split_hands(notes)
        bar_ticks = divisions * beats_per_bar
        n_measures = self._layout(notes, bar_ticks)
        self._clip_overlaps(notes)
        fifths, mode, key_name = _estimate_key(perf, opts.key_hint)
        xml = self._write(notes, n_measures, divisions, beats_per_bar, fifths, mode)
        return ScoreDoc(musicxml=xml, alignment=None, key=key_name, warnings=warnings)

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def _split_hands(notes: list[QuantizedNote]) -> None:
        pitches = np.array([n.pitch for n in notes], dtype=float)
        best_threshold, best_cost = 60.0, float("inf")
        for threshold in np.arange(45.0, 73.5, 0.5):
            low = pitches[pitches < threshold]
            high = pitches[pitches >= threshold]
            if low.size == 0 or high.size == 0:
                continue
            cost = float(np.var(low) * low.size + np.var(high) * high.size)
            if cost < best_cost - 1e-9:
                best_threshold, best_cost = float(threshold), cost
        for note in notes:
            note.staff = 1 if note.pitch >= best_threshold else 2

    @staticmethod
    def _layout(notes: list[QuantizedNote], bar_ticks: int) -> int:
        n_measures = 1
        for note in notes:
            note.measure = int(note.start_tick // bar_ticks) + 1
            n_measures = max(n_measures, note.measure, int((note.end_tick - 1) // bar_ticks) + 1)
        counters: dict[tuple[int, int], int] = {}
        for note in sorted(notes, key=lambda n: (n.staff, n.start_tick, n.pitch, n.end_tick)):
            key = (note.staff, note.measure)
            note.index = counters.get(key, 0)
            counters[key] = note.index + 1
        return n_measures

    @staticmethod
    def _clip_overlaps(notes: list[QuantizedNote]) -> None:
        for staff in (1, 2):
            staff_notes = sorted(
                [n for n in notes if n.staff == staff], key=lambda n: (n.start_tick, n.pitch)
            )
            for note, following in zip(staff_notes, staff_notes[1:], strict=False):
                if note.end_tick > following.start_tick:
                    note.end_tick = following.start_tick

    # -------------------------------------------------------------- xml write
    def _write(
        self,
        notes: list[QuantizedNote],
        n_measures: int,
        divisions: int,
        beats_per_bar: int,
        fifths: int,
        mode: str,
    ) -> bytes:
        from xml.etree import ElementTree as ET

        bar_ticks = divisions * beats_per_bar
        root = ET.Element("score-partwise", version="4.0")
        part_list = ET.SubElement(root, "part-list")
        score_part = ET.SubElement(part_list, "score-part", id="P1")
        ET.SubElement(score_part, "part-name").text = "Piano"
        part = ET.SubElement(root, "part", id="P1")
        measures = [ET.SubElement(part, "measure", number=str(n)) for n in range(1, n_measures + 1)]
        attrs = ET.SubElement(measures[0], "attributes")
        ET.SubElement(attrs, "divisions").text = str(divisions)
        key_el = ET.SubElement(attrs, "key")
        ET.SubElement(key_el, "fifths").text = str(fifths)
        ET.SubElement(key_el, "mode").text = mode
        time_el = ET.SubElement(attrs, "time")
        ET.SubElement(time_el, "beats").text = str(beats_per_bar)
        ET.SubElement(time_el, "beat-type").text = "4"
        ET.SubElement(attrs, "staves").text = "2"
        for number, sign, line in ((1, "G", "2"), (2, "F", "4")):
            clef = ET.SubElement(attrs, "clef", number=str(number))
            ET.SubElement(clef, "sign").text = sign
            ET.SubElement(clef, "line").text = line

        # Segment every note at barlines, with ties and stable ids.
        by_measure: dict[int, list[QuantizedNote]] = {n: [] for n in range(1, n_measures + 1)}
        for note in notes:
            base_id = f"n{note.staff}-{note.measure}-{note.index}"
            cursor = note.start_tick
            seg_index = 0
            while cursor < note.end_tick:
                measure_number = int(cursor // bar_ticks) + 1
                measure_end = measure_number * bar_ticks
                end = min(note.end_tick, measure_end)
                is_first, is_last = seg_index == 0, end >= note.end_tick
                tie = (
                    None
                    if is_first and is_last
                    else ("both" if not is_first and not is_last else ("stop" if not is_first else "start"))
                )
                note_id = base_id if seg_index == 0 else f"{base_id}-t{seg_index + 1}"
                note.segments.append(
                    (measure_number, cursor - (measure_number - 1) * bar_ticks, end - cursor, tie, note_id)
                )
                by_measure.setdefault(measure_number, []).append(note)
                cursor = end
                seg_index += 1

        for measure_number in range(1, n_measures + 1):
            measure = measures[measure_number - 1]
            for staff in (1, 2):
                if staff == 2:
                    # Rewind to the start of the bar so both staves share a timeline.
                    backup = ET.SubElement(measure, "backup")
                    ET.SubElement(backup, "duration").text = str(bar_ticks)
                entries = []
                for note in by_measure.get(measure_number, []):
                    if note.staff != staff:
                        continue
                    for seg in note.segments:
                        if seg[0] == measure_number:
                            entries.append((note, seg))
                entries.sort(key=lambda e: (e[1][1], e[0].pitch))
                cursor = 0
                for note, (_, rel_start, dur, tie, note_id) in entries:
                    if rel_start > cursor:
                        self._rest(measure, rel_start - cursor, staff, divisions)
                        cursor = rel_start
                    if dur > 0:
                        self._note(measure, note, dur, tie, note_id, staff, fifths, divisions)
                        cursor = rel_start + dur
                if cursor < bar_ticks:
                    self._rest(measure, bar_ticks - cursor, staff, divisions)
        ET.indent(root)
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _note_type(duration: int, divisions: int) -> str:
        ratio = duration / max(1, divisions)
        for value, name in NOTE_TYPES:
            if abs(ratio - value) < 0.02:
                return name
        return "quarter"

    def _note(
        self,
        measure: object,
        note: QuantizedNote,
        dur: int,
        tie: str | None,
        note_id: str,
        staff: int,
        fifths: int,
        divisions: int,
    ) -> None:
        from xml.etree import ElementTree as ET

        step, alter, octave = _spell(note.pitch, fifths)
        el = ET.SubElement(measure, "note", id=note_id)  # type: ignore[arg-type]
        pitch = ET.SubElement(el, "pitch")
        ET.SubElement(pitch, "step").text = step
        if alter:
            ET.SubElement(pitch, "alter").text = str(alter)
        ET.SubElement(pitch, "octave").text = str(octave)
        ET.SubElement(el, "duration").text = str(dur)
        if tie in ("start", "both"):
            ET.SubElement(el, "tie", type="start")
        if tie in ("stop", "both"):
            ET.SubElement(el, "tie", type="stop")
        ET.SubElement(el, "voice").text = "1"
        ET.SubElement(el, "type").text = self._note_type(dur, divisions)
        if tie:
            notations = ET.SubElement(el, "notations")
            if tie in ("start", "both"):
                ET.SubElement(notations, "tied", type="start")
            if tie in ("stop", "both"):
                ET.SubElement(notations, "tied", type="stop")
        ET.SubElement(el, "staff").text = str(staff)

    def _rest(self, measure: object, dur: int, staff: int, divisions: int) -> None:
        from xml.etree import ElementTree as ET

        el = ET.SubElement(measure, "note")  # type: ignore[arg-type]
        ET.SubElement(el, "rest")
        ET.SubElement(el, "duration").text = str(dur)
        ET.SubElement(el, "voice").text = "1"
        ET.SubElement(el, "type").text = self._note_type(dur, divisions)
        ET.SubElement(el, "staff").text = str(staff)

    def _empty_score(self, warnings: list[str], opts: ScoreOptions) -> ScoreDoc:
        from xml.etree import ElementTree as ET

        root = ET.Element("score-partwise", version="4.0")
        part_list = ET.SubElement(root, "part-list")
        score_part = ET.SubElement(part_list, "score-part", id="P1")
        ET.SubElement(score_part, "part-name").text = "Piano"
        part = ET.SubElement(root, "part", id="P1")
        measure = ET.SubElement(part, "measure", number="1")
        attrs = ET.SubElement(measure, "attributes")
        ET.SubElement(attrs, "divisions").text = "16"
        key_el = ET.SubElement(attrs, "key")
        ET.SubElement(key_el, "fifths").text = "0"
        time_el = ET.SubElement(attrs, "time")
        ET.SubElement(time_el, "beats").text = "4"
        ET.SubElement(time_el, "beat-type").text = "4"
        ET.SubElement(attrs, "staves").text = "2"
        for staff in (1, 2):
            note = ET.SubElement(measure, "note")
            ET.SubElement(note, "rest", measure="yes")
            ET.SubElement(note, "duration").text = "64"
            ET.SubElement(note, "voice").text = "1"
            ET.SubElement(note, "staff").text = str(staff)
        ET.indent(root)
        return ScoreDoc(musicxml=ET.tostring(root, encoding="utf-8", xml_declaration=True), warnings=warnings)
