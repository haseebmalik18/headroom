"""Deterministic benchmark: start -> tests -> load -> metrics -> teardown -> JSON.

The runner only executes and measures. It never decides whether a change is good;
that is the evaluator's job (and never the model's).
"""

import asyncio
import json
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import httpx

from hotpath.benchmark.results import BenchmarkResult, LoadReport, LoadRun, SpanStats, parse_junit
from hotpath.config import ProjectConfig, Workload, load_config, parse_duration
from hotpath.execution.docker import CommandError, ComposeProject, project_name
from hotpath.telemetry.collector import ContainerStatsSampler
from hotpath.telemetry.postgres import PostgresActivitySampler

Log = Callable[[str], None]


def _noop(_: str) -> None:
    pass


async def run_benchmark(
    repo: Path,
    *,
    label: str = "baseline",
    workloads: list[Workload] | None = None,
    run_tests: bool = True,
    collect_stats: bool = True,
    db_activity: bool = False,
    out_dir: Path = Path(".hotpath/runs"),
    keep: bool = False,
    log: Log = _noop,
) -> BenchmarkResult:
    repo = Path(repo).resolve()
    config = load_config(repo)
    workloads = workloads or [config.workload]

    name = project_name(label)
    results_dir = (Path(out_dir) / name).resolve()
    results_dir.mkdir(parents=True, exist_ok=True)
    # Containers write their reports here as their own users (k6 runs as uid 12345). Docker
    # Desktop ignores bind-mount ownership, but Linux hosts enforce it.
    results_dir.chmod(0o777)
    project =ComposeProject(repo, config.runtime.compose_file, name, results_dir)

    result = BenchmarkResult(
        service=config.service,
        label=label,
        repo=str(repo),
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        objective=config.objective,
    )

    try:
        log(f"starting {config.service} ({name})")
        try:
            await project.up(config.runtime.app_service)
        except CommandError as exc:
            # The compose output only says the container exited; the traceback is in its own logs.
            logs = await project.logs(config.runtime.app_service)
            result.error = (f"service failed to start; last lines of the {config.runtime.app_service} logs:\n{logs}"
                            if logs else f"service failed to start: {exc}")
            return result

        if run_tests:
            log("running tests")
            result.tests = await _run_tests(project, config, results_dir)
            log(f"tests: {result.tests.passed}/{result.tests.total} passed")
            if result.tests.total == 0:
                result.error = "test suite did not run"
                return result

        for index, workload in enumerate(workloads, start=1):
            log(f"load {index}/{len(workloads)}: {workload.concurrency} concurrent, think {workload.think_ms:g}ms, "
                f"{workload.duration} after {workload.warmup} warmup")
            run = await _run_load(project, config, workload, results_dir, collect_stats, db_activity,
                                  label=f"load-{index}-c{workload.concurrency}")
            result.runs.append(run)
            log(f"load: p99 {run.load.p99_ms:.1f}ms, {run.load.throughput_rps:.1f} rps, "
                f"errors {run.load.error_rate:.2%}")
    except CommandError as exc:
        result.error = str(exc)
    except httpx.HTTPError as exc:
        logs = await project.logs(config.runtime.app_service)
        result.error = f"service stopped responding ({exc!r}); last lines of the {config.runtime.app_service} logs:\n{logs}"
    finally:
        result.finished_at = datetime.now(timezone.utc)
        (results_dir / "result.json").write_text(result.model_dump_json(indent=2))
        if not keep:
            log("tearing down")
            await project.down()

    return result


async def _run_tests(project: ComposeProject, config: ProjectConfig, results_dir: Path):
    junit = results_dir / "junit.xml"
    junit.unlink(missing_ok=True)
    run = await project.run(
        config.runtime.tests_service,
        "pytest", "-q", "-p", "no:cacheprovider", "--junitxml=/results/junit.xml",
        check=False,
    )
    (results_dir / "tests.log").write_text(run.output)
    if not junit.exists():
        raise CommandError(["pytest"], run.returncode, run.output)
    return parse_junit(junit.read_text())


async def _run_load(project: ComposeProject, config: ProjectConfig, workload: Workload,
                    results_dir: Path, collect_stats: bool, db_activity: bool, label: str) -> LoadRun:
    runtime = config.runtime
    app_url = f"http://127.0.0.1:{project.app_port}"

    containers = {"app": await project.container_id(runtime.app_service)}
    if runtime.db_service:
        containers["db"] = await project.container_id(runtime.db_service)
    sampler = ContainerStatsSampler({k: v for k, v in containers.items() if v and collect_stats})
    db_sampler = PostgresActivitySampler(project, runtime.db_service) if db_activity and runtime.db_service else None

    async def start_measuring() -> None:
        # Server-side spans and container stats cover the measured window only.
        await asyncio.sleep(parse_duration(workload.warmup))
        if runtime.metrics_path:
            async with httpx.AsyncClient() as client:
                await client.post(f"{app_url}{runtime.metrics_path}/reset", timeout=10)
        sampler.start()
        if db_sampler:
            db_sampler.start()

    measuring = asyncio.create_task(start_measuring())
    try:
        k6 = await project.run(
            runtime.load_service,
            "run", "--no-color", "--quiet", runtime.load_script,
            env={
                "VUS": str(workload.concurrency),
                "THINK_MS": f"{workload.think_ms:g}",
                "WARMUP": workload.warmup,
                "DURATION": workload.duration,
                "LABEL": label,
            },
            timeout=parse_duration(workload.warmup) + parse_duration(workload.duration) + 300,
            check=False,
        )
        await measuring
    finally:
        measuring.cancel()
        usage = await sampler.stop()
        activity = await db_sampler.stop() if db_sampler else None

    (results_dir / f"{label}.log").write_text(k6.output)
    summary = results_dir / f"k6-{label}.json"
    if not summary.exists():
        raise CommandError(["k6", "run", runtime.load_script], k6.returncode, k6.output)

    spans: dict[str, SpanStats] = {}
    if runtime.metrics_path:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{app_url}{runtime.metrics_path}", timeout=30)
        response.raise_for_status()
        metrics = response.json()
        (results_dir / f"server-{label}.json").write_text(json.dumps(metrics, indent=2))
        spans = {name: SpanStats.model_validate(s) for name, s in metrics.get("spans", {}).items()}

    return LoadRun(
        load=LoadReport.model_validate_json(summary.read_text()),
        spans=spans,
        containers=usage,
        db_activity=activity,
    )
