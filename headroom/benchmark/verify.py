"""Statistical verification: repeat the benchmark and summarize it as distributions."""

from pydantic import BaseModel

from headroom.benchmark.results import BenchmarkResult
from headroom.benchmark.statistics import Comparison, Distribution, compare, describe
from headroom.config import Objective


class RunStatistics(BaseModel):
    label: str
    runs: int
    tests_passed: int | None
    tests_total: int | None
    metric: Distribution          # the objective metric (e.g. p99_ms) across runs
    throughput_rps: Distribution
    error_rate_max: float
    memory_mb_max: float | None
    slo_met_runs: int             # how many individual runs met the target


class VerificationReport(BaseModel):
    objective: Objective
    baseline: RunStatistics | None
    candidate: RunStatistics
    metric_comparison: Comparison | None
    throughput_comparison: Comparison | None
    slo_recovered: bool           # the candidate's whole confidence interval meets the target
    error: str | None = None


def summarize(result: BenchmarkResult, objective: Objective) -> RunStatistics:
    if not result.runs:
        raise ValueError(f"{result.label}: no load runs to summarize ({result.error or 'unknown error'})")
    metric_values = [getattr(r.load, objective.metric) for r in result.runs]
    memory = [r.containers["app"].memory_mb_max for r in result.runs if "app" in r.containers]
    return RunStatistics(
        label=result.label,
        runs=len(result.runs),
        tests_passed=result.tests.passed if result.tests else None,
        tests_total=result.tests.total if result.tests else None,
        metric=describe(metric_values),
        throughput_rps=describe([r.load.throughput_rps for r in result.runs]),
        error_rate_max=max(r.load.error_rate for r in result.runs),
        memory_mb_max=max(memory) if memory else None,
        slo_met_runs=sum(objective.met(v) for v in metric_values),
    )


def build_report(
    candidate: BenchmarkResult, objective: Objective, baseline: BenchmarkResult | None = None
) -> VerificationReport:
    cand = summarize(candidate, objective)
    base = summarize(baseline, objective) if baseline else None
    return VerificationReport(
        objective=objective,
        baseline=base,
        candidate=cand,
        metric_comparison=compare(base.metric, cand.metric) if base else None,
        throughput_comparison=compare(base.throughput_rps, cand.throughput_rps) if base else None,
        # The whole interval must meet the target: its worst end decides.
        slo_recovered=objective.met(cand.metric.ci_low if objective.higher_is_better else cand.metric.ci_high)
        and bool(candidate.tests and candidate.tests.ok),
    )
