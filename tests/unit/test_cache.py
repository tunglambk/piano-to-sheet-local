"""Cache keys, atomic writes and reuse (spec §5.3)."""

from __future__ import annotations

import json
from pathlib import Path

from p2s.core.cache import Cache


def test_key_is_stable_and_input_sensitive(tmp_path: Path) -> None:
    cache = Cache(tmp_path)
    key1 = cache.compute_key(input_sha256="a" * 64, stage="s3", engine_id="e", engine_version="1")
    key2 = cache.compute_key(input_sha256="a" * 64, stage="s3", engine_id="e", engine_version="1")
    key3 = cache.compute_key(input_sha256="b" * 64, stage="s3", engine_id="e", engine_version="1")
    assert key1 == key2
    assert key1 != key3


def test_key_covers_engine_weights_and_params(tmp_path: Path) -> None:
    cache = Cache(tmp_path)
    base = dict(input_sha256="a" * 64, stage="s3", engine_id="e", engine_version="1")
    a = cache.compute_key(**base)
    b = cache.compute_key(**base, weights_sha256={"w": "1" * 64})
    c = cache.compute_key(**base, params={"grid": "1/8"})
    d = cache.compute_key(**base, parent_keys=["x", "y"])
    assert len({a, b, c, d}) == 4


def test_put_get_round_trip(tmp_path: Path) -> None:
    cache = Cache(tmp_path)
    key = cache.compute_key(input_sha256="a" * 64, stage="s1", engine_id="e", engine_version="1")
    assert cache.get(key) is None
    cache.put(key, {"payload.json": b'{"x":1}'}, meta={"stage": "s1"})
    entry = cache.get(key)
    assert entry is not None
    assert json.loads(entry.read_bytes("payload.json")) == {"x": 1}
    assert entry.meta["stage"] == "s1"


def test_second_put_keeps_first_entry(tmp_path: Path) -> None:
    cache = Cache(tmp_path)
    key = cache.compute_key(input_sha256="a" * 64, stage="s1", engine_id="e", engine_version="1")
    cache.put(key, {"payload.json": b"first"})
    cache.put(key, {"payload.json": b"second"})
    entry = cache.get(key)
    assert entry is not None
    assert entry.read_bytes("payload.json") == b"first"
