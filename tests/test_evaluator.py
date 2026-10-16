from datetime import datetime, timezone

from hotpath.benchmark.evaluator import evaluate
from hotpath.benchmark.results import (
    BenchmarkResult,
    ContainerUsage,
    LoadReport,
    LoadRun,
    TestFailure,
    TestReport,
)
from hotpath.config import Constraints, Objective

OBJECTIVE = Objective(endpoint="POST /inventory/reserve", metric="p99_ms", target=100)
CONSTRAINTS = Constraints(max_error_rate=0.001, max_memory_mb=1024)


def _result(
    label: str,
    *,
    p99: float | None,
    rps: float = 100.0,
    passed: int = 17,
    total: int = 17,
    error_rate: float = 0.0,
    memory_mb: float = 80.0,
    error: str | None = None,
    failures: list[TestFailure] | None = None,
) -> BenchmarkResult:
    now = datetime.now(timezone.utc)
    runs = []
    if p99 is not None:
        load = LoadReport(
            label="load-500", vus=500, think_ms=2000, duration_s=30, requests=int(rps * 30),
            p50_ms=p99 / 2, p95_ms=p99 * 0.9, p99_ms=p99, max_ms=p99 * 1.2, avg_ms=p99 / 2,
            throughput_rps=rps, error_rate=error_rate,
        )
        runs = [LoadRun(load=load, containers={
            "app": ContainerUsage(cpu_percent_avg=40, cpu_percent_max=60, memory_mb_max=memory_mb, samples=5)
        })]
    tests = TestReport(
        total=total, passed=passed, failed=total - passed, errors=0, skipped=0, duration_s=2.0,
        failures=failures or [],
    ) if total else None
    return BenchmarkResult(
        service="checkout-service", label=label, repo="/repo", started_at=now, finished_at=now,
        objective=OBJECTIVE, tests=tests, runs=runs, error=error,
    )


def _evaluate(**candidates):
    baseline = _result("baseline", p99=428.0, rps=88.0)
    return evaluate(baseline, candidates, OBJECTIVE, CONSTRAINTS)


def test_fastest_candidate_loses_when_its_tests_fail():
    oversell = TestFailure(
        name="tests.test_inventory_concurrency::test_concurrent_reservations_never_oversell[0]",
        message="AssertionError: expected exactly 10 successful reservations, got 60",
    )
    evaluation = _evaluate(
        a=_result("a", p99=190.0, rps=150.0),
        b=_result("b", p99=71.0, rps=240.0),
        c=_result("c", p99=44.0, rps=250.0, passed=11, failures=[oversell]),
    )

    assert evaluation.winner == "b"
    assert evaluation.fastest_rejected == "c"
    by_name = {c.name: c for c in evaluation.candidates}
    assert by_name["c"].status == "rejected"
    assert any("1 test" in r or "tests failed" in r for r in by_name["c"].reasons)
    assert by_name["c"].failing_tests == [oversell.name]
    assert by_name["a"].status == "valid"
    assert by_name["b"].status == "winner"
    assert evaluation.slo_recovered is True


def test_improvement_is_relative_to_baseline():
    evaluation = _evaluate(b=_result("b", p99=71.0, rps=240.0))

    b = evaluation.candidates[0]
    assert b.p99_change_pct == round((71.0 - 428.0) / 428.0 * 100, 1)
    assert b.throughput_change_pct == round((240.0 - 88.0) / 88.0 * 100, 1)
    assert b.meets_slo is True


def test_rejects_hard_constraint_violations():
    evaluation = _evaluate(
        crashed=_result("crashed", p99=None, total=0, error="service failed to start: exit 1"),
        errors=_result("errors", p99=50.0, error_rate=0.05),
        bloated=_result("bloated", p99=50.0, memory_mb=2048),
        no_load=_result("no_load", p99=None),
    )

    by_name = {c.name: c for c in evaluation.candidates}
    assert all(c.status == "rejected" for c in evaluation.candidates)
    assert "service failed to start" in by_name["crashed"].reasons[0]
    assert any("error rate" in r for r in by_name["errors"].reasons)
    assert any("memory" in r for r in by_name["bloated"].reasons)
    assert any("no load" in r.lower() for r in by_name["no_load"].reasons)
    assert evaluation.winner is None
    assert evaluation.slo_recovered is False


def test_no_winner_when_nothing_beats_baseline():
    evaluation = _evaluate(slower=_result("slower", p99=500.0))

    assert evaluation.winner is None
    assert evaluation.candidates[0].status == "valid"
    assert any("not faster than baseline" in r for r in evaluation.candidates[0].notes)


def test_valid_winner_that_misses_slo_does_not_recover_it():
    evaluation = _evaluate(a=_result("a", p99=190.0))

    assert evaluation.winner == "a"
    assert evaluation.slo_recovered is False


def test_throughput_breaks_p99_ties():
    evaluation = _evaluate(x=_result("x", p99=70.0, rps=200.0), y=_result("y", p99=70.0, rps=240.0))

    assert evaluation.winner == "y"


def test_repeated_runs_are_judged_on_their_median():
    noisy = _result("noisy", p99=40.0, rps=240.0)
    spike = noisy.runs[0].model_copy(update={"load": noisy.runs[0].load.model_copy(update={"p99_ms": 300.0})})
    steady = noisy.runs[0].model_copy(update={"load": noisy.runs[0].load.model_copy(update={"p99_ms": 45.0})})
    noisy = noisy.model_copy(update={"runs": [noisy.runs[0], spike, steady]})

    evaluation = _evaluate(noisy=noisy)

    c = evaluation.candidates[0]
    assert c.runs == 3
    assert c.p99_ms == 45.0
    assert c.meets_slo
    assert evaluation.slo_recovered


def test_fastest_rejected_is_none_when_fastest_is_valid():
    evaluation = _evaluate(b=_result("b", p99=40.0), c=_result("c", p99=60.0, passed=16))

    assert evaluation.winner == "b"
    assert evaluation.fastest_rejected is None
