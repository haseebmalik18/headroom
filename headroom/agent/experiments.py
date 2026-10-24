"""Executing a model-designed experiment against the real system.

Nemotron decides *what* to measure; Headroom decides *how*, runs it, and returns
plain numbers. Instruments that the plan did not ask for are left out of the
evidence, so the model has to choose what to look at.
"""

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from headroom.agent.schemas import ExperimentPlan
from headroom.benchmark.results import BenchmarkResult, DbActivity
from headroom.benchmark.runner import run_benchmark
from headroom.config import Workload, load_config

MAX_CONCURRENCY = 1000


class SpanSummary(BaseModel):
    p50_ms: float
    p99_ms: float
    count: int | None = None  # how many times the span ran in the measured window


class LevelObservation(BaseModel):
    concurrency: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    throughput_rps: float
    error_rate: float
    requests: int | None = None  # measured requests, and the window they ran in
    duration_s: float | None = None
    container_cpu_percent: dict[str, float] | None = None
    container_memory_mb: dict[str, float] | None = None
    spans: dict[str, SpanSummary] | None = None
    db: DbActivity | None = None


class ExperimentResult(BaseModel):
    plan: ExperimentPlan
    levels: list[LevelObservation]
    error: str | None = None

    def render(self) -> str:
        """Compact, model-readable evidence."""
        if self.error:
            return f"Experiment failed: {self.error}"
        lines = ["concurrency | p50 ms | p99 ms | rps | errors | requests measured"]
        for lv in self.levels:
            measured = f"{lv.requests} in {lv.duration_s:g}s" if lv.requests is not None and lv.duration_s else "-"
            lines.append(f"{lv.concurrency} | {lv.p50_ms:.1f} | {lv.p99_ms:.1f} | {lv.throughput_rps:.1f} | "
                         f"{lv.error_rate:.2%} | {measured}")
        for lv in self.levels:
            details = []
            if lv.container_cpu_percent is not None:
                cpu = ", ".join(f"{k} {v:.0f}%" for k, v in lv.container_cpu_percent.items())
                mem = ", ".join(f"{k} {v:.0f} MB" for k, v in (lv.container_memory_mb or {}).items())
                details.append(f"container CPU: {cpu}; memory: {mem}")
            if lv.db is not None:
                db = lv.db
                waits = ", ".join(f"{k} x{v}" for k, v in list(db.wait_events.items())[:5]) or "none"
                details.append(
                    f"database: active connections avg {db.active_connections_avg} (max {db.active_connections_max}) "
                    f"of {db.pool_connections_max} open; idle-in-transaction avg {db.idle_in_transaction_avg}; "
                    f"transactions/s (all, incl. driver housekeeping) {db.commits_per_s}; wait events: {waits}"
                )
            if lv.spans is not None:
                top = sorted(lv.spans.items(), key=lambda kv: -kv[1].p99_ms)
                details.append("app spans (p50/p99 ms, calls in the window): " + "; ".join(
                    f"{name} {s.p50_ms:.1f}/{s.p99_ms:.1f}" + (f" ({s.count} calls)" if s.count is not None else "")
                    for name, s in top
                ))
            if details:
                lines.append(f"\nAt {lv.concurrency} concurrent:")
                lines += [f"- {d}" for d in details]
        return "\n".join(lines)


def observations(result: BenchmarkResult, plan: ExperimentPlan) -> list[LevelObservation]:
    wanted = set(plan.measurements)
    levels = []
    for run in result.runs:
        load = run.load
        obs = LevelObservation(
            concurrency=load.concurrency, p50_ms=load.p50_ms, p95_ms=load.p95_ms, p99_ms=load.p99_ms,
            throughput_rps=load.throughput_rps, error_rate=load.error_rate,
            requests=load.requests, duration_s=load.duration_s,
        )
        if "container_resources" in wanted and run.containers:
            obs.container_cpu_percent = {k: v.cpu_percent_avg for k, v in run.containers.items()}
            obs.container_memory_mb = {k: v.memory_mb_max for k, v in run.containers.items()}
        if "app_spans" in wanted:
            obs.spans = {
                name: SpanSummary(p50_ms=s.p50_ms, p99_ms=s.p99_ms, count=s.count)
                for name, s in run.spans.items() if not name.startswith("http GET /health")
            }
        if "db_activity" in wanted:
            obs.db = run.db_activity
        levels.append(obs)
    return levels


def normalize_levels(levels: list[int]) -> list[int]:
    return sorted({min(max(1, c), MAX_CONCURRENCY) for c in levels})


async def run_experiment(
    repo: Path,
    plan: ExperimentPlan,
    *,
    warmup: str = "5s",
    duration: str = "20s",
    out_dir: Path = Path(".headroom/runs"),
    log: Callable[[str], None] = lambda _: None,
) -> ExperimentResult:
    base: Workload = load_config(repo).workload
    workloads = [base.model_copy(update={"concurrency": c, "warmup": warmup, "duration": duration})
                 for c in normalize_levels(plan.concurrency_levels)]
    result = await run_benchmark(
        repo,
        label="experiment",
        workloads=workloads,
        run_tests=False,
        collect_stats="container_resources" in plan.measurements,
        db_activity="db_activity" in plan.measurements,
        out_dir=out_dir,
        log=log,
    )
    return ExperimentResult(plan=plan, levels=observations(result, plan), error=result.error)
