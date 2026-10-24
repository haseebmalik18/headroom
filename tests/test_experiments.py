from datetime import datetime, timezone

from headroom.agent.experiments import ExperimentResult, normalize_levels, observations
from headroom.agent.schemas import ExperimentPlan, Prediction
from headroom.benchmark.results import BenchmarkResult, ContainerUsage, DbActivity, LoadReport, LoadRun, SpanStats
from headroom.config import Objective


def _plan(measurements) -> ExperimentPlan:
    return ExperimentPlan(
        rationale="If the database were saturated, its CPU and active connections would climb with load.",
        concurrency_levels=[100, 500],
        measurements=measurements,
        predictions=[Prediction(observation="db CPU at 500", if_supported="> 80%", if_refuted="< 30%")],
    )


def _result() -> BenchmarkResult:
    now = datetime.now(timezone.utc)

    def run(c: int, p99: float) -> LoadRun:
        return LoadRun(
            load=LoadReport(label=f"l{c}", vus=c, think_ms=2000, duration_s=20, requests=100, p50_ms=p99 / 2,
                            p95_ms=p99, p99_ms=p99, max_ms=p99, avg_ms=p99 / 2, throughput_rps=c / 2,
                            error_rate=0.0),
            spans={
                "inventory.lock_wait": SpanStats(count=9, mean_ms=1, p50_ms=3600, p95_ms=3800, p99_ms=3830, max_ms=3900),
                "db.select_stock": SpanStats(count=9, mean_ms=1, p50_ms=1.1, p95_ms=2, p99_ms=2.7, max_ms=3),
                "http GET /health": SpanStats(count=9, mean_ms=1, p50_ms=1, p95_ms=1, p99_ms=40, max_ms=40),
            },
            containers={"app": ContainerUsage(cpu_percent_avg=35, cpu_percent_max=40, memory_mb_max=70, samples=4),
                        "db": ContainerUsage(cpu_percent_avg=12, cpu_percent_max=15, memory_mb_max=34, samples=4)},
            db_activity=DbActivity(samples=10, active_connections_avg=1.0, active_connections_max=1,
                                   idle_in_transaction_avg=0.0, pool_connections_max=20, commits_per_s=88.0,
                                   wait_events={"Client:ClientRead": 7, "CPU:running": 3}),
        )

    return BenchmarkResult(service="s", label="experiment", repo="/r", started_at=now, finished_at=now,
                           objective=Objective(endpoint="POST /x", target=100), runs=[run(100, 80), run(500, 3850)])


def test_only_requested_instruments_are_reported():
    levels = observations(_result(), _plan(["db_activity", "container_resources"]))

    assert [lv.concurrency for lv in levels] == [100, 500]
    assert levels[1].db.active_connections_avg == 1.0
    assert levels[1].container_cpu_percent == {"app": 35, "db": 12}
    assert levels[1].spans is None            # not requested, so the model does not see lock_wait


def test_spans_when_requested_skip_healthchecks():
    levels = observations(_result(), _plan(["app_spans"]))

    assert set(levels[1].spans) == {"inventory.lock_wait", "db.select_stock"}
    assert levels[1].db is None


def test_render_includes_numbers_for_requested_instruments():
    plan = _plan(["db_activity", "container_resources"])
    text = ExperimentResult(plan=plan, levels=observations(_result(), plan)).render()

    assert "500 | 1925.0 | 3850.0" in text
    assert "active connections avg 1.0 (max 1) of 20 open" in text
    assert "db 12%" in text
    assert "lock_wait" not in text


def test_normalize_levels_clamps_and_dedupes():
    assert normalize_levels([500, 0, 25, 500, 5000]) == [1, 25, 500, 1000]


def test_render_gives_counts_so_rates_can_be_worked_out():
    plan = _plan(["app_spans"])
    text = ExperimentResult(plan=plan, levels=observations(_result(), plan)).render()

    assert "500 | 1925.0 | 3850.0 | 250.0 | 0.00% | 100 in 20s" in text
    assert "inventory.lock_wait 3600.0/3830.0 (9 calls)" in text
