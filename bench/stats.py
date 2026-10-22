"""Bootstrap statistics for benchmark numbers (spec §6.4)."""

from __future__ import annotations

import random
from statistics import mean, median

SEED = 20261020


def bootstrap_ci(
    values: list[float], resamples: int = 10_000, alpha: float = 0.05, seed: int = SEED
) -> tuple[float, float]:
    if not values:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(values)
    means = sorted(mean(rng.choices(values, k=n)) for _ in range(resamples))
    return means[int(alpha / 2 * resamples)], means[int((1 - alpha / 2) * resamples) - 1]


def summarize(name: str, values: dict[str, float | None]) -> dict:
    scored = [v for v in values.values() if v is not None]
    out: dict[str, object] = {
        "system": name,
        "n_items": len(values),
        "n_fail": len(values) - len(scored),
        "n_scored": len(scored),
    }
    if scored:
        low, high = bootstrap_ci(scored)
        out.update(
            {
                "mean": round(mean(scored), 2),
                "median": round(median(scored), 2),
                "ci95": [round(low, 2), round(high, 2)],
                "min": round(min(scored), 2),
                "max": round(max(scored), 2),
            }
        )
    return out


def paired_diff(
    a: dict[str, float | None], b: dict[str, float | None], resamples: int = 10_000, seed: int = SEED
) -> dict:
    keys = sorted(set(a) & set(b))
    diffs = [a[k] - b[k] for k in keys if a[k] is not None and b[k] is not None]
    if not diffs:
        return {"n_pairs": 0}
    rng = random.Random(seed)
    means = sorted(mean(rng.choices(diffs, k=len(diffs))) for _ in range(resamples))
    return {
        "n_pairs": len(diffs),
        "mean_diff": round(mean(diffs), 2),
        "ci95": [round(means[250], 2), round(means[-250], 2)],
        "win_rate": round(sum(1 for d in diffs if d < 0) / len(diffs), 3),
    }
