"""Shared pytest setup: markers, fixture paths and the offline guard (NFR-01)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SMOKE = REPO / "data" / "fixtures" / "smoke"


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "gpu: needs a CUDA GPU")
    config.addinivalue_line("markers", "sidecar: needs a running sidecar")


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO


@pytest.fixture(scope="session")
def smoke_audio() -> Path:
    path = SMOKE / "fast_passage.wav"
    if not path.exists():
        pytest.skip("smoke fixtures missing; generate them locally (see docs/ci.md)")
    return path


@pytest.fixture(scope="session")
def smoke_manifest() -> dict:
    import json

    path = REPO / "tests" / "fixtures" / "smoke.json"
    if not path.exists():
        pytest.skip("smoke fixture manifest missing")
    return json.loads(path.read_text())


class _SocketGuard:
    """Fail on non-loopback connections during CPU tests (no telemetry, NFR-01)."""

    def __init__(self) -> None:
        self._original = socket.socket.connect
        self.hits: list[tuple[str, int]] = []

    def enable(self) -> None:
        def connect(sock: socket.socket, address):  # type: ignore[no-untyped-def]
            host = address[0] if isinstance(address, tuple) else str(address)
            if host not in ("127.0.0.1", "::1", "localhost"):
                self.hits.append((host, address[1] if isinstance(address, tuple) else 0))
                raise RuntimeError(f"network access to {host} is not allowed in tests (NFR-01)")
            return self._original(sock, address)

        socket.socket.connect = connect  # type: ignore[assignment]

    def disable(self) -> None:
        socket.socket.connect = self._original  # type: ignore[assignment]


@pytest.fixture
def offline_guard():
    guard = _SocketGuard()
    guard.enable()
    try:
        yield guard
    finally:
        guard.disable()
