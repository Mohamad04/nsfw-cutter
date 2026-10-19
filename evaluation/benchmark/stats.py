"""Uncertainty helpers in pure Python (no SciPy): Wilson intervals, exact McNemar and grouped bootstrap."""
from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Callable, Sequence

Z95 = 1.959963984540054


def wilson(successes: int, total: int, z: float = Z95):
    """Wilson score interval for a binomial proportion; None when total is zero."""
    if total == 0:
        return None
    if not 0 <= successes <= total:
        raise ValueError("successes must lie between 0 and total")
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return {"estimate": p, "low": max(0.0, centre - half), "high": min(1.0, centre + half),
            "successes": successes, "total": total, "method": "wilson"}


def mcnemar_exact(only_first_correct: int, only_second_correct: int):
    """Two-sided exact McNemar test on discordant pairs (binomial, p = 0.5)."""
    discordant = only_first_correct + only_second_correct
    if discordant == 0:
        return {"b": 0, "c": 0, "discordant": 0, "p_value": None, "method": "exact_binomial"}
    k = min(only_first_correct, only_second_correct)
    tail = sum(math.comb(discordant, i) for i in range(k + 1)) / 2 ** discordant
    return {"b": only_first_correct, "c": only_second_correct, "discordant": discordant,
            "p_value": min(1.0, 2 * tail), "method": "exact_binomial"}


def holm(p_values: dict[str, float | None]):
    """Holm step-down adjustment; untestable comparisons (None) stay None."""
    tested = sorted((p, name) for name, p in p_values.items() if p is not None)
    adjusted, running = {}, 0.0
    for rank, (p, name) in enumerate(tested):
        running = max(running, min(1.0, (len(tested) - rank) * p))
        adjusted[name] = running
    return {name: adjusted.get(name) for name in p_values}


def grouped_bootstrap(rows: Sequence[dict], group_key: str, statistic: Callable[[list[dict]], float | None],
                      *, resamples: int = 5000, seed: int = 20261019, confidence: float = 0.95):
    """Percentile interval resampling whole independence groups with replacement.

    Resamples where the statistic is undefined (e.g. no positive left) are counted, not hidden.
    """
    groups = defaultdict(list)
    for row in rows:
        groups[row[group_key]].append(row)
    names = sorted(groups)
    estimate = statistic(list(rows))
    result = {"estimate": estimate, "groups": len(names), "rows": len(rows), "resamples": resamples,
              "seed": seed, "confidence": confidence, "undefined_resamples": 0, "low": None, "high": None,
              "method": f"grouped_bootstrap_percentile:{group_key}"}
    if not names or estimate is None:
        return result
    rng, values = random.Random(seed), []
    for _ in range(resamples):
        sample = [row for _ in names for row in groups[names[rng.randrange(len(names))]]]
        value = statistic(sample)
        if value is None:
            result["undefined_resamples"] += 1
        else:
            values.append(value)
    if values:
        values.sort()
        alpha = (1 - confidence) / 2
        result["low"] = _quantile(values, alpha)
        result["high"] = _quantile(values, 1 - alpha)
    return result


def _quantile(sorted_values: list[float], q: float) -> float:
    position = q * (len(sorted_values) - 1)
    lower, upper = math.floor(position), math.ceil(position)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
