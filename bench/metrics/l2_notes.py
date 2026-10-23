"""L2 note metrics: onset F1, note F1, pitch accuracy (spec §6.5).

Scored against the Performance the system heard, using a tolerance window and
optimal matching (each predicted onset matches at most one reference onset).
"""

from __future__ import annotations

from p2s.core.schemas import Performance

TOLERANCE_S = 0.05


def _match(predicted: list[tuple[float, int]], reference: list[tuple[float, int]], tol: float) -> int:
    used = [False] * len(reference)
    hits = 0
    for onset, pitch in predicted:
        best, best_cost = -1, tol
        for index, (ref_onset, ref_pitch) in enumerate(reference):
            if used[index] or ref_pitch != pitch:
                continue
            cost = abs(onset - ref_onset)
            if cost <= best_cost:
                best, best_cost = index, cost
        if best >= 0:
            used[best] = True
            hits += 1
    return hits


def _f1(hits: int, predicted: int, reference: int) -> float:
    if not predicted or not reference:
        return 0.0
    precision = hits / predicted
    recall = hits / reference
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def evaluate(
    predicted: Performance, reference: Performance, tolerance: float = TOLERANCE_S
) -> dict[str, float]:
    ref_onsets = sorted((note.onset, note.pitch) for note in reference.notes)
    pred_onsets = sorted((note.onset, note.pitch) for note in predicted.notes)
    onset_hits = _match(pred_onsets, ref_onsets, tolerance)
    ref_notes = sorted((note.onset, note.pitch) for note in reference.notes)
    pred_notes = sorted((note.onset, note.pitch) for note in predicted.notes)
    note_hits = _match(pred_notes, ref_notes, tolerance)
    pitch_hits = _match(
        [(0.0, pitch) for _, pitch in pred_notes], [(0.0, pitch) for _, pitch in ref_notes], 1e9
    )
    return {
        "onset_f1": round(_f1(onset_hits, len(pred_onsets), len(ref_onsets)), 4),
        "note_f1": round(_f1(note_hits, len(pred_notes), len(ref_notes)), 4),
        "pitch_f1": round(_f1(pitch_hits, len(pred_notes), len(ref_notes)), 4),
        "n_predicted": len(pred_notes),
        "n_reference": len(ref_notes),
    }
