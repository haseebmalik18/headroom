"""Deterministic statistics over repeated benchmark runs.

One lucky run proves nothing. Verification repeats the benchmark and reports the
median with a bootstrap confidence interval; two results are only called
different when their intervals do not overlap.
"""

import random
import statistics

from pydantic import BaseModel

RESAMPLES = 10_000


class Distribution(BaseModel):
    n: int
    values: list[float]
    median: float
    mean: float
    stdev: float
    ci_low: float
    ci_high: float
    confidence: float


class Comparison(BaseModel):
    baseline: Distribution
    candidate: Distribution
    median_change_pct: float
    separated: bool  # confidence intervals do not overlap


def bootstrap_ci(values: list[float], confidence: float = 0.95, seed: int = 0) -> tuple[float, float]:
    """Percentile bootstrap confidence interval for the median."""
    if len(values) == 1:
        return values[0], values[0]
    rng = random.Random(seed)
    n = len(values)
    medians = sorted(statistics.median(rng.choices(values, k=n)) for _ in range(RESAMPLES))
    tail = (1 - confidence) / 2
    low = medians[int(tail * RESAMPLES)]
    high = medians[min(RESAMPLES - 1, int((1 - tail) * RESAMPLES))]
    return low, high


def describe(values: list[float], confidence: float = 0.95, seed: int = 0) -> Distribution:
    if not values:
        raise ValueError("cannot describe an empty sample")
    low, high = bootstrap_ci(values, confidence, seed)
    return Distribution(
        n=len(values),
        values=list(values),
        median=statistics.median(values),
        mean=statistics.fmean(values),
        stdev=statistics.stdev(values) if len(values) > 1 else 0.0,
        ci_low=low,
        ci_high=high,
        confidence=confidence,
    )


def compare(baseline: Distribution, candidate: Distribution) -> Comparison:
    change = (candidate.median - baseline.median) / baseline.median * 100 if baseline.median else 0.0
    separated = candidate.ci_high < baseline.ci_low or candidate.ci_low > baseline.ci_high
    return Comparison(
        baseline=baseline,
        candidate=candidate,
        median_change_pct=round(change, 1),
        separated=separated,
    )
