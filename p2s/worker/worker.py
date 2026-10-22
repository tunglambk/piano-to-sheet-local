"""Worker loop: claim a job, run it in a child process, honour cancel (plan step 3).

The parent never imports torch. It claims, heartbeats, watches for a cancel
request, and turns "child exited non-zero" into a failed job. The child writes
its own status on success.
"""

from __future__ import annotations

import multiprocessing
import signal
import threading
from pathlib import Path

from sqlmodel import Session

from p2s.core.db import Job, emit, init_db, utcnow
from p2s.worker.executor import run_job
from p2s.worker.queue import SqliteQueue, new_worker_id


class Worker:
    def __init__(
        self,
        data_dir: Path,
        poll_s: float = 0.4,
        cancel_grace_s: float = 2.0,
        method: str = "spawn",
    ) -> None:
        self.data_dir = Path(data_dir)
        self.engine = init_db(self.data_dir)
        self.queue = SqliteQueue(self.engine)
        self.poll_s = poll_s
        self.cancel_grace_s = cancel_grace_s
        self.worker_id = new_worker_id()
        self.method = method
        self._stop = threading.Event()
        self._process: object | None = None

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ run
    def run(self, once: bool = False) -> None:
        context = multiprocessing.get_context(self.method)
        while not self._stop.is_set():
            self.queue.reap_stale()
            job = self.queue.claim(self.worker_id)
            if job is None:
                if once:
                    return
                self._stop.wait(self.poll_s)
                continue
            self._run_one(context, job)
            if once:
                return

    def _run_one(self, context, job: Job) -> None:  # noqa: ANN001 - mp context
        process = context.Process(target=run_job, args=(job.id, str(self.data_dir)), daemon=False)
        process.start()
        self._process = process
        cancelled = False
        while process.is_alive():
            if self.queue.is_cancelled(job.id):
                cancelled = True
                self._terminate(process)
                break
            self.queue.heartbeat(job.id)
            process.join(self.poll_s)
        process.join()
        self._process = None
        if cancelled:
            self.queue.cancel(job.id)
            self._end_event(job.id, "cancelled", None)
            return
        if process.exitcode not in (0, None):
            self.queue.fail(job.id, f"worker child exited with code {process.exitcode}")
            self._end_event(job.id, "failed", f"worker child exited with code {process.exitcode}")

    def _terminate(self, process) -> None:  # noqa: ANN001 - mp process
        try:
            process.terminate()
            process.join(self.cancel_grace_s)
            if process.is_alive():
                process.kill()
                process.join(2.0)
        except (ProcessLookupError, ValueError):
            pass

    def _end_event(self, job_id: str, status: str, error: str | None) -> None:
        with Session(self.engine) as session:
            job = session.get(Job, job_id)
            if job is None:
                return
            job.updated_at = utcnow()
            session.add(job)
            emit(session, job, "end", {"status": status, "error": error})
            session.commit()


def run_worker(data_dir: Path, once: bool = False) -> None:
    worker = Worker(data_dir)

    def _stop(_signum, _frame):  # noqa: ANN001
        worker.stop()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    worker.run(once=once)
