"""A job's title and composer reach the pipeline (D-131)."""

from __future__ import annotations

from p2s.worker.executor import _labels


def test_title_and_composer_are_read() -> None:
    assert _labels({"title": "Clair de lune", "composer": "Claude Debussy"}) == (
        "Clair de lune",
        "Claude Debussy",
    )


def test_missing_or_blank_values_become_none() -> None:
    assert _labels({}) == (None, None)
    assert _labels({"title": "   ", "composer": ""}) == (None, None)


def test_extra_parameters_are_ignored() -> None:
    assert _labels({"title": "X", "composer": "Y", "device": "cuda", "seed": 1}) == ("X", "Y")
