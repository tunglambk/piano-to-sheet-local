"""SQLite persistence for the API and the worker (spec §5.3).

One file, WAL mode, short transactions. SQLModel models are the schema; the MVP
creates tables with `create_all` and records the schema version, alembic arrives
with the release phase (D-031). Nothing here feeds artifact content, so the
pipeline's determinism is unaffected.
"""

from __future__ import annotations

import json
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import event as sa_event
from sqlalchemy.engine import Engine as SAEngine
from sqlmodel import Field, Session, SQLModel, create_engine

SCHEMA_VERSION = 1
ACTIVE_STATES = ("queued", "running")
TERMINAL_STATES = ("succeeded", "failed", "cancelled")


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    """ULID-like, sortable id: milliseconds + 80 random bits, Crockford base32."""
    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    digits = []
    for _ in range(26):
        digits.append(alphabet[value & 31])
        value >>= 5
    return "".join(reversed(digits))


class Job(SQLModel, table=True):
    id: str = Field(primary_key=True)
    name: str = ""
    status: str = "queued"
    preset: str = "accurate"
    params_json: str = "{}"
    range_json: str | None = None
    input_sha256: str = ""
    input_path: str = ""
    origin_offset_s: float = 0.0
    duration_s: float = 0.0
    error: str | None = None
    cancel_requested: bool = False
    worker_id: str | None = None
    heartbeat_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    def params(self) -> dict[str, Any]:
        return json.loads(self.params_json or "{}")

    def range(self) -> dict[str, Any] | None:
        return json.loads(self.range_json) if self.range_json else None


class StageRun(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    stage: str
    engine: str = ""
    engine_version: str = ""
    cache_key: str = ""
    cache_hit: bool = False
    status: str = "running"
    duration_s: float = 0.0
    detail_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)


class Artifact(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    revision_id: str | None = None
    kind: str
    name: str = ""
    path: str
    size: int = 0
    sha256: str = ""


class Revision(SQLModel, table=True):
    id: str = Field(primary_key=True, default_factory=new_id)
    job_id: str = Field(index=True)
    parent_id: str | None = None
    kind: str = "manual"
    payload_json: str = "{}"
    created_at: datetime = Field(default_factory=utcnow)


class JobEvent(SQLModel, table=True):
    seq: int | None = Field(default=None, primary_key=True)
    job_id: str = Field(index=True)
    ts: datetime = Field(default_factory=utcnow)
    type: str
    payload_json: str = "{}"

    def payload(self) -> dict[str, Any]:
        return json.loads(self.payload_json or "{}")


class SchemaVersion(SQLModel, table=True):
    version: int = Field(primary_key=True)
    applied_at: datetime = Field(default_factory=utcnow)


def database_url(data_dir: Path) -> str:
    return f"sqlite:///{Path(data_dir) / 'p2s.db'}"


def make_engine(url: str) -> SAEngine:
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @sa_event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_connection, _record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def init_db(data_dir: Path) -> SAEngine:
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(database_url(data_dir))
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.get(SchemaVersion, SCHEMA_VERSION) is None:
            session.add(SchemaVersion(version=SCHEMA_VERSION))
            session.commit()
    return engine


def emit(session: Session, job: Job, type_: str, payload: dict[str, Any] | None = None) -> None:
    """Append a job event and bump the job's updated_at, in the caller's transaction."""
    session.add(JobEvent(job_id=job.id, type=type_, payload_json=json.dumps(payload or {}, sort_keys=True)))
    job.updated_at = utcnow()
