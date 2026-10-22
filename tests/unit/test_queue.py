"""Queue and worker tests (plan steps 2-3)."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from sqlmodel import Session

from p2s.core.db import Job, init_db, utcnow
from p2s.worker import worker as worker_module
from p2s.worker.queue import SqliteQueue, new_worker_id
from p2s.worker.worker import Worker


def make_jobs(engine, count: int) -> list[str]:
    ids = []
    with Session(engine) as session:
        for index in range(count):
            job = Job(id=f"01JOB{index:021d}", name=f"job {index}", status="queued", input_path="/tmp/x.wav")
            session.add(job)
            ids.append(job.id)
        session.commit()
    return ids


def test_claim_never_hands_out_the_same_job(tmp_path: Path) -> None:
    engine = init_db(tmp_path)
    make_jobs(engine, 4)
    queue = SqliteQueue(engine)
    claimed: list[str] = []
    lock = threading.Lock()

    def grab() -> None:
        for _ in range(4):
            job = queue.claim(new_worker_id())
            if job is not None:
                with lock:
                    claimed.append(job.id)

    threads = [threading.Thread(target=grab) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(claimed) == 4
    assert len(set(claimed)) == 4


def test_claim_returns_none_when_empty(tmp_path: Path) -> None:
    queue = SqliteQueue(init_db(tmp_path))
    assert queue.claim(new_worker_id()) is None


def test_cancel_flag_round_trip(tmp_path: Path) -> None:
    engine = init_db(tmp_path)
    job_id = make_jobs(engine, 1)[0]
    queue = SqliteQueue(engine)
    assert queue.is_cancelled(job_id) is False
    assert queue.request_cancel(job_id) is True
    assert queue.is_cancelled(job_id) is True
    queue.complete(job_id)
    assert queue.request_cancel(job_id) is False


def test_stale_worker_is_failed_not_requeued(tmp_path: Path) -> None:
    engine = init_db(tmp_path)
    job_id = make_jobs(engine, 1)[0]
    queue = SqliteQueue(engine)
    queue.claim(new_worker_id())
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        job.heartbeat_at = utcnow().replace(year=2020)
        session.add(job)
        session.commit()
    assert queue.reap_stale(timeout_s=60) == [job_id]
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "failed"
        assert job.error == "worker lost"


def test_worker_runs_a_job_in_a_child_process(tmp_path: Path, monkeypatch) -> None:
    def fake_run(job_id: str, data_dir: str) -> int:
        engine = init_db(Path(data_dir))
        with Session(engine) as session:
            job = session.get(Job, job_id)
            assert job is not None
            job.status = "succeeded"
            session.add(job)
            session.commit()
        return 0

    monkeypatch.setattr(worker_module, "run_job", fake_run)
    engine = init_db(tmp_path)
    job_id = make_jobs(engine, 1)[0]
    worker = Worker(tmp_path, poll_s=0.1, method="fork")
    worker.run(once=True)
    deadline = time.time() + 10
    while time.time() < deadline:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job and job.status == "succeeded":
                return
        time.sleep(0.1)
    raise AssertionError("the child never marked the job as succeeded")


def test_worker_marks_a_crashed_child_as_failed(tmp_path: Path, monkeypatch) -> None:
    def boom(job_id: str, data_dir: str) -> int:
        raise RuntimeError("engine exploded")

    monkeypatch.setattr(worker_module, "run_job", boom)
    engine = init_db(tmp_path)
    job_id = make_jobs(engine, 1)[0]
    worker = Worker(tmp_path, poll_s=0.1, method="fork")
    worker.run(once=True)
    deadline = time.time() + 10
    while time.time() < deadline:
        with Session(engine) as session:
            job = session.get(Job, job_id)
            if job and job.status == "failed":
                break
        time.sleep(0.1)
    with Session(engine) as session:
        job = session.get(Job, job_id)
        assert job is not None
        assert job.status == "failed"
        assert "exited" in (job.error or "")
