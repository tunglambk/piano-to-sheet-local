"""Engine contract and data models (spec §5.2, D-023).

This module depends only on Pydantic so sidecars can install it with `--no-deps`.
Everything crossing a module or process boundary is one of these models: no
ad-hoc dicts (AGENTS.md).

Times are float seconds relative to the *original* input file, never to the
trimmed range. A stage that receives an `AudioRef` with `origin_offset_s > 0`
must add that offset to every time it emits; `AudioRef.to_original(t)` does it.
"""

from __future__ import annotations

import base64
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator

SCHEMA_VERSION = "1.0"

Device = Literal["cpu", "cuda", "mps"]
EngineKind = Literal["inprocess", "sidecar", "external"]
CommercialUse = Literal["yes", "no", "unknown"]
QuantizeGrid = Literal["1/8", "1/16", "1/32"]


class AudioRef(BaseModel):
    """A decoded audio file plus its provenance."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="Path relative to the data root")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    sample_rate: int = Field(gt=0)
    channels: int = Field(gt=0)
    duration_s: float = Field(gt=0)
    origin_offset_s: float = Field(default=0.0, ge=0.0)

    def to_original(self, t: float) -> float:
        """Convert a time measured from the start of this file to original-file seconds."""
        return self.origin_offset_s + t


class EngineInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    version: str
    weights_sha256: dict[str, str] = Field(default_factory=dict)
    code_license: str
    weight_license: str
    commercial_use: CommercialUse = "unknown"
    device: str = "cpu"
    kind: EngineKind = "inprocess"
    schema_version: str = SCHEMA_VERSION


class NoteEvent(BaseModel):
    pitch: int = Field(ge=21, le=108, description="MIDI pitch")
    onset: float = Field(ge=0.0)
    offset: float = Field(ge=0.0)
    velocity: int = Field(ge=1, le=127)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_interval(self) -> NoteEvent:
        if self.offset < self.onset:
            raise ValueError(f"offset {self.offset} < onset {self.onset}")
        return self


class Performance(BaseModel):
    notes: list[NoteEvent] = Field(default_factory=list)
    pedals: list[tuple[float, float]] = Field(
        default_factory=list, description="sustain CC64 (on, off) seconds"
    )
    engine: EngineInfo

    @field_validator("pedals")
    @classmethod
    def _check_pedals(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        for on, off in v:
            if off < on:
                raise ValueError(f"pedal off {off} < on {on}")
        return v


class BeatGrid(BaseModel):
    beats: list[float] = Field(default_factory=list)
    downbeats: list[float] = Field(default_factory=list)
    time_signatures: list[tuple[float, str]] = Field(default_factory=list)
    tempo_bpm: list[tuple[float, float]] = Field(default_factory=list)
    engine: EngineInfo


class ScoreDoc(BaseModel):
    """A two-staff score plus the note-id → performance-time alignment (S7)."""

    musicxml: bytes
    alignment: dict[str, tuple[float, float]] | None = None
    key: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @field_serializer("musicxml")
    def _b64(self, value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    @field_validator("musicxml", mode="before")
    @classmethod
    def _unb64(cls, value: object) -> bytes:
        if isinstance(value, str):
            return base64.b64decode(value)
        return value  # type: ignore[return-value]


class AMTOptions(BaseModel):
    device: Device = "cpu"
    with_pedal: bool = True
    min_note_s: float = Field(default=0.0, ge=0.0)
    onset_threshold: float | None = None


class MeterHints(BaseModel):
    bpm: float | None = Field(default=None, gt=0)
    time_signature: str | None = None
    first_downbeat_s: float | None = Field(default=None, ge=0)


class ScoreOptions(BaseModel):
    quantize_grid: QuantizeGrid = "1/16"
    allow_triplets: bool = True
    key_hint: str | None = None
    time_signature_hint: str | None = None
    pedal_marks: bool = True
    dynamics_from_velocity: bool = True
    seed: int = 0


class IngestOptions(BaseModel):
    start_s: float | None = Field(default=None, ge=0)
    end_s: float | None = Field(default=None, gt=0)
    normalize_loudness: bool = True

    @model_validator(mode="after")
    def _check_range(self) -> IngestOptions:
        if self.start_s is not None and self.end_s is not None and self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")
        return self


@runtime_checkable
class Engine(Protocol):
    def info(self) -> EngineInfo: ...
    def close(self) -> None: ...


@runtime_checkable
class Separator(Engine, Protocol):
    def separate(self, audio: AudioRef, stem: Literal["piano"]) -> AudioRef: ...


@runtime_checkable
class Transcriber(Engine, Protocol):
    def transcribe(self, audio: AudioRef, opts: AMTOptions) -> Performance: ...


@runtime_checkable
class BeatTracker(Engine, Protocol):
    def track(self, audio: AudioRef, hints: MeterHints) -> BeatGrid: ...


@runtime_checkable
class ScoreBuilder(Engine, Protocol):
    def build(self, perf: Performance, grid: BeatGrid, opts: ScoreOptions) -> ScoreDoc: ...


@runtime_checkable
class EndToEnd(Engine, Protocol):
    def transcribe_score(self, audio: AudioRef, opts: ScoreOptions) -> ScoreDoc: ...
