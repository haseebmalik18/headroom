from datetime import datetime, timezone

from headroom.benchmark.results import (
    BenchmarkResult,
    ContainerUsage,
    LoadReport,
    LoadRun,
    SpanStats,
    TestReport,
)
from headroom.config import Objective


def _load(p99: float, concurrency: int = 500) -> LoadReport:
    return LoadReport(
        label=f"load-{concurrency}",
        vus=concurrency,
        think_ms=2000,
        duration_s=30,
        requests=2600,
        p50_ms=p99 * 0.9,
        p95_ms=p99 * 0.98,
        p99_ms=p99,
        max_ms=p99 * 1.1,
        avg_ms=p99 * 0.9,
        throughput_rps=88.5,
        error_rate=0.0,
    )


def _result(p99: float) -> BenchmarkResult:
    now = datetime.now(timezone.utc)
    return BenchmarkResult(
        service="checkout-service",
        label="baseline",
        repo="/repo",
        started_at=now,
        finished_at=now,
        objective=Objective(endpoint="POST /inventory/reserve", metric="p99_ms", target=100),
        tests=TestReport(total=17, passed=17, failed=0, errors=0, skipped=0, duration_s=3.1, failures=[]),
        runs=[
            LoadRun(
                load=_load(p99),
                spans={"inventory.lock_wait": SpanStats(count=10, mean_ms=1, p50_ms=1, p95_ms=2, p99_ms=337, max_ms=400)},
                containers={
                    "app": ContainerUsage(cpu_percent_avg=44.0, cpu_percent_max=60.0, memory_mb_max=542.0, samples=5),
                    "db": ContainerUsage(cpu_percent_avg=12.0, cpu_percent_max=15.0, memory_mb_max=34.0, samples=5),
                },
            )
        ],
    )


def test_summary_is_flat_and_uses_app_container():
    summary = _result(428.0).summary()

    assert summary["p99_ms"] == 428.0
    assert summary["throughput_rps"] == 88.5
    assert summary["error_rate"] == 0.0
    assert summary["memory_mb"] == 542.0
    assert summary["cpu_percent"] == 44.0
    assert summary["tests_passed"] == 17
    assert summary["tests_total"] == 17
    assert summary["span_p99_ms"] == {"inventory.lock_wait": 337}
    assert summary["slo_met"] is False


def test_slo_met_when_under_target():
    assert _result(72.0).slo_met is True
    assert _result(428.0).slo_met is False


def test_failed_run_has_no_slo_verdict():
    result = _result(72.0).model_copy(update={"runs": [], "error": "service failed to start"})

    assert result.slo_met is None
    assert result.summary()["error"] == "service failed to start"
