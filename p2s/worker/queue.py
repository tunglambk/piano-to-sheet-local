"""Job queue on SQLite (spec §5.3, plan step 2).

`claim` is a single atomic statement, so two workers can never take the same
job. A job whose worker stopped heartbeating is failed as "worker lost" instead
of being retried silently: a half-written cache entry is worse than a clear error.
"""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Protocol

from sqlalchemy import desc, text
from sqlmodel import Session, select

from p2s.core.db import Job, StageRun, utcnow

STALE_AFTER_S = 60.0


class JobQueue(Protocol):
    def claim(self, worker_id: str) -> Job | None: ...
    def heartbeat(self, job_id: str) -> None: ...
    def is_cancelled(self, job_id: str) -> bool: ...
    def request_cancel(self, job_id: str) -> bool: ...
    def complete(self, job_id: str) -> None: ...
    def fail(self, job_id: str, error: str) -> None: ...


def new_worker_id(prefix: str = "w") -> str:
    return f"{prefix}-{secrets.token_hex(4)}"


class SqliteQueue:
    def __init__(self, engine) -> None:  # noqa: ANN001 - SQLAlchemy engine
        self.engine = engine

    def claim(self, worker_id: str) -> Job | None:
        now = utcnow()
        with self.engine.begin() as connection:
            row = connection.execute(
                text(
                    """
                    UPDATE job
                       SET status = 'running', worker_id = :worker, heartbeat_at = :now, updated_at = :now
                     WHERE id = (SELECT id FROM job WHERE status = 'queued' ORDER BY created_at LIMIT 1)
                       AND status = 'queued'
                    RETURNING id
                    """
                ),
                {"worker": worker_id, "now": now},
            ).first()
        if row is None:
            return None
        with Session(self.engine) as session:
            return session.get(Job, row[0])

    def heartbeat(self, job_id: str) -> None:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is not None:
                job.heartbeat_at = utcnow()
                session.add(job)
                session.commit()

    def is_cancelled(self, job_id: str) -> bool:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            return bool(job and job.cancel_requested)

    def request_cancel(self, job_id: str) -> bool:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None or job.status in ("succeeded", "failed", "cancelled"):
                return False
            job.cancel_requested = True
            job.updated_at = utcnow()
            session.add(job)
            session.commit()
            return True

    def complete(self, job_id: str) -> None:
        self._finish(job_id, "succeeded", None)

    def fail(self, job_id: str, error: str) -> None:
        self._finish(job_id, "failed", error)

    def cancel(self, job_id: str) -> None:
        self._finish(job_id, "cancelled", None)

    def _finish(self, job_id: str, status: str, error: str | None) -> None:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            job.status = status
            job.error = error
            job.heartbeat_at = utcnow()
            job.updated_at = utcnow()
            session.add(job)
            session.commit()

    def reap_stale(self, timeout_s: float = STALE_AFTER_S) -> list[str]:
        """Fail running jobs whose worker stopped heartbeating."""
        cutoff = utcnow() - timedelta(seconds=timeout_s)
        failed: list[str] = []
        with Session(self.engine) as session:
            jobs = session.exec(select(Job).where(Job.status == "running")).all()
            for job in jobs:
                if job.heartbeat_at is None or job.heartbeat_at < cutoff:
                    job.status = "failed"
                    job.error = "worker lost"
                    job.updated_at = utcnow()
                    session.add(job)
                    failed.append(job.id)
            session.commit()
        return failed

    def running_stage(self, job_id: str) -> StageRun | None:
        with Session(self.engine) as session:
            return session.exec(
                select(StageRun).where(StageRun.job_id == job_id).order_by(desc("id")).limit(1)
            ).first()
