"""A job submitted through the API reaches the pipeline with its labels (D-131).

The pipeline itself is replaced by a recorder: the point of this test is the wiring
between the job row and `Pipeline.run`, which the benchmark, the CLI and the unit
suite all skip — the reason the missing title survived so long.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session

from p2s.core.db import Job, init_db
from p2s.worker import executor


class _Recorder:
    captured: dict = {}

    def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        self.__dict__["_args"] = args

    def run(self, input_path, preset, ingest, score, hints, **kwargs):  # noqa: ANN001, ANN003
        _Recorder.captured = {"input_path": str(input_path), "preset": preset, **kwargs}

        class _Result:
            manifest: dict = {}
            stage_keys: dict = {}

        return _Result()

    def artifact(self, name: str):
        raise KeyError(name)


class _RecorderFailure(RuntimeError):
    """The recorder has no artefacts past `run`, which is where the job stops."""


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    init_db(tmp_path)
    return tmp_path


def _job(data_dir: Path, params: dict) -> str:
    inputs = data_dir / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    audio = inputs / "clip.wav"
    audio.write_bytes(b"RIFF0000WAVEfmt ")
    job_id = "job-test"
    engine = init_db(data_dir)
    with Session(engine) as session:
        session.add(
            Job(
                id=job_id,
                preset="fast",
                params_json=json.dumps(params),
                input_path=str(audio),
            )
        )
        session.commit()
    return job_id


def test_title_and_composer_reach_the_pipeline(data_dir: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(executor, "Pipeline", _Recorder)
    job_id = _job(data_dir, {"title": "Clair de lune", "composer": "Claude Debussy"})
    _Recorder.captured = {}
    with pytest.raises((KeyError, AttributeError)):
        executor.run_job(job_id, str(data_dir))
    assert _Recorder.captured.get("title") == "Clair de lune"
    assert _Recorder.captured.get("composer") == "Claude Debussy"
    assert _Recorder.captured.get("preset") == "fast"


def test_absent_labels_stay_none(data_dir: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(executor, "Pipeline", _Recorder)
    job_id = _job(data_dir, {})
    _Recorder.captured = {}
    with pytest.raises((KeyError, AttributeError)):
        executor.run_job(job_id, str(data_dir))
    assert _Recorder.captured.get("title") is None
    assert _Recorder.captured.get("composer") is None
