"""Content-addressed cache (spec §5.3, NFR-05).

Key = sha256 over canonical JSON of the stage inputs:
{input_sha256, stage, engine_id, engine_version, weights_sha256, params, parent_keys}

Entries live at `data/cache/<key[:2]>/<key>/` and contain `meta.json` plus the
stage artifacts. Writes are atomic (temp dir + rename) and guarded by a file lock,
so two workers cannot publish a half-written entry.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class CacheEntry:
    key: str
    dir: Path
    meta: dict[str, Any]

    def file(self, name: str) -> Path:
        path = self.dir / name
        if not path.exists():
            raise FileNotFoundError(f"cache entry {self.key} has no artifact {name!r}")
        return path

    def read_json(self, name: str) -> Any:
        return json.loads(self.file(name).read_text())

    def read_bytes(self, name: str) -> bytes:
        return self.file(name).read_bytes()


class Cache:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / ".tmp").mkdir(exist_ok=True)
        self._lock_path = self.root / ".lock"

    # ------------------------------------------------------------------ keys
    def compute_key(
        self,
        *,
        input_sha256: str,
        stage: str,
        engine_id: str,
        engine_version: str,
        weights_sha256: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        parent_keys: list[str] | None = None,
    ) -> str:
        payload = {
            "input_sha256": input_sha256,
            "stage": stage,
            "engine_id": engine_id,
            "engine_version": engine_version,
            "weights_sha256": weights_sha256 or {},
            "params": params or {},
            "parent_keys": sorted(parent_keys or []),
        }
        return sha256_bytes(canonical_json(payload).encode("utf-8"))

    # -------------------------------------------------------------- storage
    def entry_dir(self, key: str) -> Path:
        return self.root / key[:2] / key

    def get(self, key: str) -> CacheEntry | None:
        directory = self.entry_dir(key)
        meta_path = directory / "meta.json"
        if not meta_path.exists():
            return None
        try:
            meta = json.loads(meta_path.read_text())
        except json.JSONDecodeError:
            return None
        return CacheEntry(key=key, dir=directory, meta=meta)

    def put(
        self,
        key: str,
        files: dict[str, bytes] | None = None,
        *,
        copy_from: dict[str, Path] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> CacheEntry:
        directory = self.entry_dir(key)
        directory.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f"{key[:12]}-", dir=self.root / ".tmp"))
        published = False
        try:
            for name, data in (files or {}).items():
                (tmp / name).write_bytes(data)
            for name, src in (copy_from or {}).items():
                shutil.copyfile(src, tmp / name)
            payload = {"key": key, **(meta or {})}
            (tmp / "meta.json").write_text(json.dumps(payload, sort_keys=True, indent=1) + "\n")
            with open(self._lock_path, "w") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                try:
                    if not directory.exists():
                        os.replace(tmp, directory)
                        published = True
                    # else: someone published it first; keep theirs
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            if not published and tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        entry = self.get(key)
        if entry is None:
            raise RuntimeError(f"cache entry {key} missing right after write")
        return entry

    def put_dir(self, key: str, source: Path, meta: dict[str, Any] | None = None) -> CacheEntry:
        """Publish a directory of artifacts as one entry (atomic)."""
        directory = self.entry_dir(key)
        directory.parent.mkdir(parents=True, exist_ok=True)
        (source / "meta.json").write_text(
            json.dumps({"key": key, **(meta or {})}, sort_keys=True, indent=1) + "\n"
        )
        with open(self._lock_path, "w") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                if not directory.exists():
                    os.replace(source, directory)
                else:
                    shutil.rmtree(source, ignore_errors=True)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        entry = self.get(key)
        if entry is None:
            raise RuntimeError(f"cache entry {key} missing right after write")
        return entry

    def stats(self) -> dict[str, int]:
        entries = sum(1 for p in self.root.glob("*/*/meta.json"))
        size = sum(p.stat().st_size for p in self.root.glob("*/*/*") if p.is_file())
        return {"entries": entries, "bytes": size}

    def tempdir(self) -> Path:
        path = self.root / ".tmp" / f"t-{uuid.uuid4().hex}"
        path.mkdir(parents=True)
        return path
