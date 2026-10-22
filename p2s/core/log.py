"""Structured logging (stdlib only).

Library code never prints. Loggers carry `job_id`, `stage` and `engine` as extra
fields so a job can be followed across stages.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_FORMAT = "%(asctime)s %(levelname)s %(name)s job=%(job_id)s stage=%(stage)s engine=%(engine)s %(message)s"


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, default in (("job_id", "-"), ("stage", "-"), ("engine", "-")):
            if not hasattr(record, key):
                setattr(record, key, default)
        return True


def configure(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.addFilter(_ContextFilter())
    root = logging.getLogger("p2s")
    root.handlers[:] = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.propagate = False


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter:
    return logging.LoggerAdapter(logging.getLogger(name), context)
