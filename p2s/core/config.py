"""Config loading: `configs/engines.yaml`, `configs/presets.yaml`, `configs/models.lock`.

Validates that every engine referenced by a preset exists in the registry and has
verified weights in the lock file. Applying D-011 (`accurate` uses Transkun only)
is done in `configs/presets.yaml`; this module only reads it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from p2s.core.errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIGS = REPO_ROOT / "configs"


class EngineSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["inprocess", "sidecar"]
    module: str | None = None
    checkpoint: str | None = None
    device: str | None = None
    url: str | None = None
    timeout_s: float = Field(default=600.0, gt=0)


class EngineRegistry(BaseModel):
    engines: dict[str, dict[str, EngineSpec]]

    def get(self, stage: str, name: str) -> EngineSpec:
        try:
            return self.engines[stage][name]
        except KeyError as exc:
            raise ConfigError(f"engine {name!r} is not registered for stage {stage!r}") from exc

    def names(self, stage: str) -> list[str]:
        return sorted(self.engines.get(stage, {}))


class EnsembleOptions(BaseModel):
    enabled: bool = False
    engines: list[str] = Field(default_factory=list)
    onset_tolerance_ms: float = 50.0
    vote: str = "keep_if_both_or_high_velocity"


class Preset(BaseModel):
    model_config = ConfigDict(extra="allow")

    extends: str | None = None
    separate: str = "auto"
    separation_threshold: float = 0.8
    amt: list[str] = Field(default_factory=list)
    amt_device: str | None = None
    amt_ensemble: EnsembleOptions = Field(default_factory=EnsembleOptions)
    beats: str = "beat_this"
    score: str = "m2st"
    fallback_score: str = "rule_quant"
    pdf: str = "musescore"


class PresetsConfig(BaseModel):
    presets: dict[str, Preset]
    defaults: dict[str, object] = Field(default_factory=dict)

    def resolve(self, name: str) -> Preset:
        """Merge `extends` chains: parent values first, child overrides second."""
        chain: list[Preset] = []
        seen: set[str] = set()
        current: Preset | None = self.presets.get(name)
        if current is None:
            raise ConfigError(f"unknown preset {name!r}; choose from {sorted(self.presets)}")
        while current is not None:
            key = current.extends or name
            if key in seen:
                raise ConfigError(f"preset inheritance cycle at {key!r}")
            seen.add(key)
            chain.append(current)
            current = self.presets.get(current.extends) if current.extends else None
        merged: dict[str, Any] = {}
        for preset in reversed(chain):
            merged.update(preset.model_dump(exclude={"extends"}, exclude_unset=True))
        return Preset(**merged)


class ModelLockEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    stage: str
    scope: str = "app"
    status: str = "candidate"
    weights: list[dict[str, str]] = Field(default_factory=list)
    code_license: str = "unknown"
    weight_license: str = "unknown"
    commercial_use: str = "unknown"

    @field_validator("commercial_use", mode="before")
    @classmethod
    def _bool_to_word(cls, value: object) -> object:
        # YAML 1.1 parses unquoted yes/no as booleans.
        if isinstance(value, bool):
            return "yes" if value else "no"
        return value


class ModelLock(BaseModel):
    version: int = 1
    entries: list[ModelLockEntry]

    def by_id(self, engine_id: str) -> ModelLockEntry | None:
        return next((e for e in self.entries if e.id == engine_id), None)


class Config(BaseModel):
    engines: EngineRegistry
    presets: PresetsConfig
    lock: ModelLock

    def preset(self, name: str) -> Preset:
        preset = self.presets.resolve(name)
        for stage, engine_name in (
            ("beats", preset.beats),
            ("score", preset.score),
            ("score", preset.fallback_score),
        ):
            self.engines.get(stage, engine_name)
        for amt in preset.amt:
            self.engines.get("amt", amt)
        return preset


def _read_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text())
    except FileNotFoundError as exc:
        raise ConfigError(f"missing config file: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc


def load_config(configs_dir: Path | None = None) -> Config:
    root = configs_dir or CONFIGS
    engines = EngineRegistry(**_read_yaml(root / "engines.yaml"))
    presets = PresetsConfig(**_read_yaml(root / "presets.yaml"))
    lock = ModelLock(**_read_yaml(root / "models.lock"))
    if not presets.presets:
        raise ConfigError("presets.yaml defines no presets")
    return Config(engines=engines, presets=presets, lock=lock)
