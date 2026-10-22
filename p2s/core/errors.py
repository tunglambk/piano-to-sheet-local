"""Typed errors. CLI exit codes map onto these (Phase 1 plan, Step 11)."""

from __future__ import annotations


class P2SError(Exception):
    """Base class; `exit_code` is what the CLI returns for it."""

    exit_code = 1


class InputError(P2SError):
    exit_code = 2


class CorruptInput(InputError):
    pass


class UnsupportedInput(InputError):
    pass


class InputTooLong(InputError):
    pass


class ConfigError(P2SError):
    exit_code = 4


class WeightsError(P2SError):
    exit_code = 4


class EngineError(P2SError):
    exit_code = 3


class StageTimeout(EngineError):
    pass


class Cancelled(P2SError):
    exit_code = 130
