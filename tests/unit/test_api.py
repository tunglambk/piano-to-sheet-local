"""API surface tests (plan step 9): upload, list, cancel, delete, events."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from p2s.api.app import create_app
from p2s.core.db import Job, init_db


@pytest.fixture
def client(tmp_path: Path, smoke_audio: Path):
    app = create_app(tmp_path)
    with TestClient(app) as test_client:
        test_client.audio = smoke_audio  # type: ignore[attr-defined]
        yield test_client


def upload(client: TestClient, name: str = "clip.wav", data: bytes | None = None, **form: str) -> dict:
    content = data if data is not None else Path(client.audio).read_bytes()  # type: ignore[attr-defined]
    response = client.post(
        "/api/v1/jobs",
        files={"file": (name, content, "audio/wav")},
        data={
            "preset": form.get("preset", "fast"),
            "params": "{}",
            "range": "{}",
            "name": form.get("name", ""),
        },
    )
    return {"status": response.status_code, "body": response.json()}


def test_health(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_creates_a_queued_job(client: TestClient) -> None:
    result = upload(client, name="my piece")
    assert result["status"] == 201
    job_id = result["body"]["job_id"]
    job = client.get(f"/api/v1/jobs/{job_id}").json()
    assert job["status"] == "queued"
    assert job["name"] == "my piece"
    assert job["duration_s"] > 1.0


def test_list_and_pagination(client: TestClient) -> None:
    for _ in range(3):
        upload(client)
    page = client.get("/api/v1/jobs?limit=2").json()
    assert len(page["jobs"]) == 2
    second = client.get(f"/api/v1/jobs?limit=2&cursor={page['next_cursor']}").json()
    assert second["jobs"]
    assert {job["id"] for job in page["jobs"]}.isdisjoint({job["id"] for job in second["jobs"]})


def test_rename_and_delete(client: TestClient) -> None:
    job_id = upload(client)["body"]["job_id"]
    assert client.patch(f"/api/v1/jobs/{job_id}", json={"name": "renamed"}).status_code == 200
    assert client.get(f"/api/v1/jobs/{job_id}").json()["name"] == "renamed"
    assert client.delete(f"/api/v1/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/v1/jobs/{job_id}").status_code == 404


def test_corrupt_upload_is_rejected_cleanly(client: TestClient) -> None:
    response = client.post("/api/v1/jobs", files={"file": ("bad.mp3", b"not audio at all", "audio/mpeg")})
    assert response.status_code in (400, 415, 422)
    assert "detail" in response.json()
    # Nothing was queued.
    assert client.get("/api/v1/jobs").json()["jobs"] == []


def test_empty_upload_is_rejected(client: TestClient) -> None:
    response = client.post("/api/v1/jobs", files={"file": ("empty.wav", b"", "audio/wav")})
    assert response.status_code in (400, 415, 422)


def test_cancel_marks_the_job(client: TestClient, tmp_path: Path) -> None:
    job_id = upload(client)["body"]["job_id"]
    assert client.post(f"/api/v1/jobs/{job_id}/cancel").json()["status"] == "cancel-requested"
    with Session(init_db(tmp_path)) as session:
        job = session.get(Job, job_id)
        assert job is not None and job.cancel_requested


def test_events_stream_starts_with_the_queued_event(client: TestClient) -> None:
    job_id = upload(client)["body"]["job_id"]
    with client.stream("GET", f"/api/v1/jobs/{job_id}/events") as response:
        assert response.status_code == 200
        lines = []
        for line in response.iter_lines():
            lines.append(line)
            if len(lines) > 6:
                break
    payload = "\n".join(lines)
    assert "event: queued" in payload
    assert "data: " in payload


def test_unknown_job_is_404(client: TestClient) -> None:
    assert client.get("/api/v1/jobs/NOPE").status_code == 404
    assert client.get("/api/v1/jobs/NOPE/artifacts/pdf").status_code == 404


def test_engines_endpoint_lists_the_catalogue(client: TestClient) -> None:
    response = client.get("/api/v1/engines")
    assert response.status_code == 200
    ids = {engine["id"] for engine in response.json()["engines"]}
    assert {"transkun_v2", "beat_this", "m2st"} <= ids


def test_openapi_is_served(client: TestClient) -> None:
    schema = client.get("/api/openapi.json").json()
    assert "/api/v1/jobs" in schema["paths"]
    assert "/api/v1/jobs/{job_id}/artifacts/{kind}" in schema["paths"]
    json.dumps(schema)  # serialisable snapshot for the web client
