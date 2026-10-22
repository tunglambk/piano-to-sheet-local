"""Determinism flags (NFR-05, R-07).

Call `setup()` once, before any torch work. CPU-only installs skip the torch part.
The flags favour reproducibility over throughput; Phase 0 showed Transkun is
already byte-identical run to run.
"""

from __future__ import annotations

import os
import random


def setup(seed: int = 0) -> None:
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    os.environ.setdefault("PYTHONHASHSEED", str(seed))
    random.seed(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
        if torch.cuda.is_available():
            torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
        torch.use_deterministic_algorithms(True, warn_only=True)
    except ImportError:
        pass
