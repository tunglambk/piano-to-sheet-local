"""Engine factory: config + lock → in-process engine or sidecar client."""

from __future__ import annotations

import importlib
from typing import Any

from p2s.core.config import Config
from p2s.core.errors import ConfigError
from p2s.core.schemas import EngineInfo
from p2s.engines.sidecar_client import SidecarClient


def create_engine(config: Config, stage: str, name: str, device: str | None = None) -> Any:
    spec = config.engines.get(stage, name)
    lock = config.lock.by_id(name)
    if lock is None and name.endswith("_small"):
        lock = config.lock.by_id(name[: -len("_small")])
    if spec.kind == "sidecar":
        if not spec.url:
            raise ConfigError(f"sidecar engine {name!r} has no url")
        return SidecarClient(name, spec.url, spec.timeout_s)
    if lock is None:
        raise ConfigError(f"engine {name!r} has no models.lock entry")
    if not spec.module:
        raise ConfigError(f"in-process engine {name!r} has no module")
    module_name, _, class_name = spec.module.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ConfigError(f"cannot import {module_name} for engine {name!r}: {exc}") from exc
    factory = getattr(module, class_name, None)
    if factory is None:
        raise ConfigError(f"{module_name} has no class {class_name!r}")
    resolved_device = device or spec.device or "cpu"
    kwargs: dict[str, object] = {}
    if name.startswith("beat_this"):
        kwargs["checkpoint"] = spec.checkpoint or ("small0" if name.endswith("small") else "final0")
    return factory(spec, lock, resolved_device, **kwargs)


def safe_info(engine) -> EngineInfo | None:
    try:
        return engine.info()
    except Exception:  # noqa: BLE001 - a missing sidecar must not hide the error
        return None
