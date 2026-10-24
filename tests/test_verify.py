from datetime import datetime, timezone

import pytest

from headroom.benchmark.results import BenchmarkResult, ContainerUsage, LoadReport, LoadRun, TestReport
from headroom.benchmark.verify import build_report, summarize
from headroom.config import Objective

OBJECTIVE = Objective(endpoint="POST /inventory/reserve", metric="p99_ms", target=100)


def _repeated(label: str, p99s: list[float], rps: float, tests_ok: bool = True) -> BenchmarkResult:
    now = datetime.now(timezone.utc)
    runs = [
        LoadRun(
            load=LoadReport(
                label=f"load-{i}", vus=500, think_ms=2000, duration_s=30, requests=100, p50_ms=p / 2,
                p95_ms=p * 0.9, p99_ms=p, max_ms=p * 1.1, avg_ms=p / 2, throughput_rps=rps + i, error_rate=0.0,
            ),
            containers={"app": ContainerUsage(cpu_percent_avg=30, cpu_percent_max=40, memory_mb_max=70 + i, samples=3)},
        )
        for i, p in enumerate(p99s)
    ]
    passed = 17 if tests_ok else 11
    return BenchmarkResult(
        service="checkout-service", label=label, repo="/r", started_at=now, finished_at=now, objective=OBJECTIVE,
        tests=TestReport(total=17, passed=passed, failed=17 - passed, errors=0, skipped=0, duration_s=1, failures=[]),
        runs=runs,
    )


BASELINE = _repeated("baseline", [3800, 3900, 4100, 4300, 3850, 3950, 4000, 4050, 3920, 3880], rps=88)
PATCHED = _repeated("atomic", [20, 18, 25, 47, 16, 19, 22, 21, 23, 20], rps=250)


def test_summarize_repeated_runs():
    stats = summarize(PATCHED, OBJECTIVE)

    assert stats.runs == 10
    assert stats.metric.median == 20.5
    assert stats.slo_met_runs == 10
    assert stats.memory_mb_max == 79
    assert stats.tests_passed == 17


def test_report_compares_against_baseline():
    report = build_report(PATCHED, OBJECTIVE, BASELINE)

    assert report.metric_comparison.median_change_pct == pytest.approx(-99.4, abs=0.1)
    assert report.metric_comparison.separated
    assert report.throughput_comparison.median_change_pct > 150
    assert report.slo_recovered


def test_slo_not_recovered_when_tests_fail():
    broken = _repeated("no-lock", [15, 14, 16], rps=250, tests_ok=False)

    assert build_report(broken, OBJECTIVE, BASELINE).slo_recovered is False


def test_slo_not_recovered_when_interval_crosses_target():
    shaky = _repeated("shaky", [60, 70, 140, 80, 150, 75, 90, 130, 65, 85], rps=200)

    assert build_report(shaky, OBJECTIVE).slo_recovered is False


def test_summarize_without_runs_raises():
    empty = BASELINE.model_copy(update={"runs": [], "error": "service failed to start"})

    with pytest.raises(ValueError, match="service failed to start"):
        summarize(empty, OBJECTIVE)
