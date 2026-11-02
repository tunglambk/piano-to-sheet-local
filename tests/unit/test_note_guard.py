"""The pipeline warns when the engraved score has fewer notes than the performance (D-101)."""

from __future__ import annotations

from p2s.core.pipeline import NOTES_MIN_RATIO


def test_threshold_is_a_sane_share() -> None:
    assert 0.5 <= NOTES_MIN_RATIO <= 1.0


def test_a_score_missing_the_left_hand_trips_the_guard() -> None:
    # The D-100 defect: 619 engraved notes for 996 performed ones.
    performed, scored = 996, 619
    assert scored < NOTES_MIN_RATIO * performed


def test_a_complete_score_does_not_trip_it() -> None:
    performed, scored = 962, 1215  # tie splitting can add notes
    assert not scored < NOTES_MIN_RATIO * performed
