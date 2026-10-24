"""Deterministic candidate evaluation.

Nemotron proposes patches; this module decides which one wins. A candidate is
rejected outright if it breaks any hard constraint (tests, startup, benchmark,
error rate, memory). Only valid candidates are ranked: best objective metric
first (lowest latency or error rate, highest throughput), then the other of latency and throughput. Speed never excuses a failed test.

When a candidate was benchmarked several times, its metrics are the medians
across those runs, and its error rate and memory are the worst seen.

With several objectives, the first is the primary one candidates are ranked on.
A candidate must meet all of them to recover the SLO, and one that breaks an
objective the original code was meeting is rejected outright.
"""

from typing import Literal

from pydantic import BaseModel

from headroom.benchmark.results import BenchmarkResult
from headroom.config import Constraints, Objective

Status = Literal["winner", "valid", "rejected"]


class CandidateEvaluation(BaseModel):
    name: str
    status: Status
    reasons: list[str] = []      # why it was rejected
    notes: list[str] = []        # non-fatal observations
    failing_tests: list[str] = []
    runs: int = 0
    metric_value: float | None = None
    p99_ms: float | None = None
    throughput_rps: float | None = None
    tests_passed: int | None = None
    tests_total: int | None = None
    meets_slo: bool = False          # every objective met
    goals_met: int = 0
    p99_change_pct: float | None = None
    throughput_change_pct: float | None = None


class Evaluation(BaseModel):
    objective: Objective                 # the primary objective
    objectives: list[Objective] = []
    baseline_metric: float | None
    baseline_throughput_rps: float | None
    candidates: list[CandidateEvaluation]
    winner: str | None
    fastest_rejected: str | None   # the quickest candidate that was thrown out, if it beat every valid one
    slo_recovered: bool


def _change_pct(new: float, old: float | None) -> float | None:
    if old is None or old == 0:
        return None
    return round((new - old) / old * 100, 1)


def _rejections(result: BenchmarkResult, constraints: Constraints) -> list[str]:
    if result.error:
        return [result.error]
    reasons = []
    if result.tests is None:
        reasons.append("tests did not run")
    elif not result.tests.ok:
        broken = result.tests.failed + result.tests.errors
        reasons.append(f"tests failed: {broken} of {result.tests.total} tests failed")
    runs = result.primary_runs
    if not runs:
        reasons.append("no load test results")
        return reasons
    error_rate = max(r.load.error_rate for r in runs)
    if error_rate > constraints.max_error_rate:
        reasons.append(f"error rate {error_rate:.2%} exceeds {constraints.max_error_rate:.2%}")
    memory = [r.containers["app"].memory_mb_max for r in runs if "app" in r.containers]
    if constraints.max_memory_mb is not None and memory and max(memory) > constraints.max_memory_mb:
        reasons.append(f"memory {max(memory):.0f} MB exceeds {constraints.max_memory_mb:.0f} MB")
    return reasons


def _regressions(result: BenchmarkResult, baseline: BenchmarkResult, goals: list[Objective]) -> list[str]:
    """Objectives the original code met and this candidate does not."""
    reasons = []
    for goal in goals:
        before, now = baseline.median_value(goal), result.median_value(goal)
        if before is not None and now is not None and goal.met(before) and not goal.met(now):
            reasons.append(f"made {goal.endpoint} miss its goal ({goal.text()}): "
                           f"{goal.show(before)} before, {goal.show(now)} now")
    return reasons


def evaluate(
    baseline: BenchmarkResult,
    candidates: dict[str, BenchmarkResult],
    objectives: Objective | list[Objective],
    constraints: Constraints,
) -> Evaluation:
    goals = [objectives] if isinstance(objectives, Objective) else list(objectives)
    objective = goals[0]
    base_metric = baseline.median_value(objective)
    base_p99 = baseline.median_load("p99_ms")
    base_rps = baseline.median_load("throughput_rps")

    evaluations: list[CandidateEvaluation] = []
    for name, result in candidates.items():
        reasons = _rejections(result, constraints)
        if not reasons:
            reasons = _regressions(result, baseline, goals)
        entry = CandidateEvaluation(
            name=name,
            status="rejected" if reasons else "valid",
            reasons=reasons,
            failing_tests=[f.name for f in result.tests.failures] if result.tests else [],
            tests_passed=result.tests.passed if result.tests else None,
            tests_total=result.tests.total if result.tests else None,
            runs=len(result.primary_runs),
        )
        metric = result.median_value(objective)
        if metric is not None:
            entry.metric_value = metric
            entry.p99_ms = result.median_load("p99_ms")
            entry.throughput_rps = result.median_load("throughput_rps")
            entry.goals_met = sum(goal.met(result.median_value(goal)) for goal in goals)
            entry.meets_slo = entry.goals_met == len(goals)
            entry.p99_change_pct = _change_pct(entry.p99_ms, base_p99)
            entry.throughput_change_pct = _change_pct(entry.throughput_rps, base_rps)
            if entry.status == "valid" and base_metric is not None and not objective.better(metric, base_metric):
                entry.notes.append("not better than baseline")
        evaluations.append(entry)

    def rank(c: CandidateEvaluation) -> tuple[float, float]:
        if objective.higher_is_better:
            return (-c.metric_value, c.p99_ms or 0)
        return (c.metric_value, -(c.throughput_rps or 0))

    eligible = [c for c in evaluations if c.status == "valid" and "not better than baseline" not in c.notes]
    winner = min(eligible, key=lambda c: (-c.goals_met, *rank(c)), default=None)
    if winner:
        winner.status = "winner"

    measured = [c for c in evaluations if c.metric_value is not None]
    fastest = min(measured, key=rank, default=None)
    fastest_rejected = fastest.name if fastest and fastest.status == "rejected" else None

    return Evaluation(
        objective=objective,
        objectives=goals,
        baseline_metric=base_metric,
        baseline_throughput_rps=base_rps,
        candidates=evaluations,
        winner=winner.name if winner else None,
        fastest_rejected=fastest_rejected,
        slo_recovered=bool(winner and winner.meets_slo),
    )
