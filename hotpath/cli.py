import asyncio
import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from hotpath.agent.schemas import PatchCandidate
from hotpath.benchmark.race import RaceReport, race
from hotpath.benchmark.results import BenchmarkResult
from hotpath.benchmark.runner import run_benchmark
from hotpath.benchmark.verify import VerificationReport, build_report
from hotpath.config import load_config
from hotpath.execution.backend import LocalExecutionBackend

app = typer.Typer(help="HotPath: an autonomous performance engineer.", no_args_is_help=True)
console = Console()


@app.callback()
def main() -> None:
    pass


@app.command()
def benchmark(
    repo: Annotated[Path, typer.Argument(help="Repository containing hotpath.yaml")],
    label: Annotated[str, typer.Option(help="Name for this run")] = "baseline",
    concurrency: Annotated[
        Optional[str], typer.Option(help="Concurrency level(s), comma-separated, e.g. 25,100,500")
    ] = None,
    think_ms: Annotated[Optional[float], typer.Option(help="Mean think time between requests")] = None,
    warmup: Annotated[Optional[str], typer.Option(help="Warmup before measuring, e.g. 10s")] = None,
    duration: Annotated[Optional[str], typer.Option(help="Measured duration, e.g. 30s")] = None,
    tests: Annotated[bool, typer.Option(help="Run the test suite first")] = True,
    stats: Annotated[bool, typer.Option(help="Sample container CPU/memory during load")] = True,
    keep: Annotated[bool, typer.Option(help="Leave the environment running afterwards")] = False,
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Write result JSON here")] = None,
) -> None:
    """Start the service, run its tests and load test, collect metrics, tear down, emit JSON."""
    base = load_config(repo).workload
    overrides = {
        k: v for k, v in {"think_ms": think_ms, "warmup": warmup, "duration": duration}.items() if v is not None
    }
    levels = [int(c) for c in concurrency.split(",")] if concurrency else [base.concurrency]
    workloads = [base.model_copy(update={**overrides, "concurrency": c}) for c in levels]

    result = asyncio.run(
        run_benchmark(
            repo,
            label=label,
            workloads=workloads,
            run_tests=tests,
            collect_stats=stats,
            keep=keep,
            log=lambda msg: console.print(f"[dim]›[/dim] {msg}"),
        )
    )

    _print_result(result)
    if output:
        output.write_text(result.model_dump_json(indent=2))
        console.print(f"[dim]full result written to {output}[/dim]")
    console.print_json(json.dumps(result.summary()))
    raise typer.Exit(1 if result.error else 0)


@app.command("race")
def race_command(
    repo: Annotated[Path, typer.Argument(help="Repository containing hotpath.yaml")],
    candidate: Annotated[
        list[str], typer.Option("--candidate", "-c", help="NAME=path/to/patch.diff (repeatable)")
    ],
    warmup: Annotated[Optional[str], typer.Option(help="Warmup before measuring, e.g. 10s")] = None,
    duration: Annotated[Optional[str], typer.Option(help="Measured duration, e.g. 30s")] = None,
    repeats: Annotated[int, typer.Option(help="Load runs per candidate; ranking uses the median")] = 3,
    parallel: Annotated[int, typer.Option(help="Candidates benchmarked at once")] = 1,
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Write race report JSON here")] = None,
) -> None:
    """Benchmark the baseline and each candidate patch in isolation, then pick a winner deterministically."""
    candidates = []
    for spec in candidate:
        name, _, path = spec.partition("=")
        candidates.append(PatchCandidate(
            name=name, strategy=f"hand-written patch {path}", expected_effect="", patch=Path(path).read_text()
        ))
    base = load_config(repo).workload
    overrides = {k: v for k, v in {"warmup": warmup, "duration": duration}.items() if v is not None}
    workloads = [base.model_copy(update=overrides)] * repeats
    log = lambda msg: console.print(f"[dim]›[/dim] {msg}")  # noqa: E731

    report = asyncio.run(race(
        repo, candidates, LocalExecutionBackend(repo, log=log), workloads=workloads, parallel=parallel, log=log,
    ))
    _print_race(report)
    if output:
        output.write_text(report.model_dump_json(indent=2))
        console.print(f"[dim]race report written to {output}[/dim]")


@app.command("verify")
def verify_command(
    repo: Annotated[Path, typer.Argument(help="Repository containing hotpath.yaml")],
    patch: Annotated[Optional[str], typer.Option(help="NAME=path/to/patch.diff to verify (default: the repo as-is)")] = None,
    runs: Annotated[int, typer.Option(help="Repeated benchmark runs for the candidate")] = 10,
    baseline_runs: Annotated[int, typer.Option(help="Repeated runs of the unpatched baseline (0 to skip)")] = 10,
    warmup: Annotated[Optional[str], typer.Option(help="Warmup before each measured run")] = None,
    duration: Annotated[Optional[str], typer.Option(help="Measured duration of each run")] = None,
    output: Annotated[Optional[Path], typer.Option("--output", "-o", help="Write verification report JSON here")] = None,
) -> None:
    """Repeat the benchmark N times and report medians with 95% bootstrap confidence intervals."""
    config = load_config(repo)
    overrides = {k: v for k, v in {"warmup": warmup, "duration": duration}.items() if v is not None}
    workload = config.workload.model_copy(update=overrides)
    log = lambda msg: console.print(f"[dim]›[/dim] {msg}")  # noqa: E731

    async def go() -> VerificationReport:
        baseline = None
        if baseline_runs:
            baseline = await run_benchmark(repo, label="baseline", workloads=[workload] * baseline_runs,
                                           log=lambda m: log(f"[baseline] {m}"))
        if patch:
            name, _, path = patch.partition("=")
            candidate = PatchCandidate(name=name, strategy=f"patch {path}", expected_effect="",
                                       patch=Path(path).read_text())
            result = (await LocalExecutionBackend(repo, log=log).evaluate_candidate(
                candidate, [workload] * runs)).result
        else:
            result = await run_benchmark(repo, label="candidate", workloads=[workload] * runs,
                                         log=lambda m: log(f"[candidate] {m}"))
        return build_report(result, config.objective, baseline)

    report = asyncio.run(go())
    _print_verification(report)
    if output:
        output.write_text(report.model_dump_json(indent=2))
        console.print(f"[dim]verification report written to {output}[/dim]")


def _print_verification(report: VerificationReport) -> None:
    metric = report.objective.metric
    table = Table(title=f"Verification · {report.objective.endpoint} {metric} < {report.objective.target:g}")
    for column in ("", "runs", "tests", f"median {metric}", "95% CI", "stdev", "median rps", "runs meeting SLO"):
        table.add_column(column, justify="right" if column else "left")
    for stats in filter(None, [report.baseline, report.candidate]):
        m = stats.metric
        table.add_row(
            stats.label, str(stats.runs),
            f"{stats.tests_passed}/{stats.tests_total}" if stats.tests_total else "-",
            f"{m.median:.1f}", f"{m.ci_low:.1f}–{m.ci_high:.1f}", f"{m.stdev:.1f}",
            f"{stats.throughput_rps.median:.1f}", f"{stats.slo_met_runs}/{stats.runs}",
        )
    console.print(table)
    if report.metric_comparison:
        c, t = report.metric_comparison, report.throughput_comparison
        console.print(f"{metric}: {c.median_change_pct:+.1f}%  ·  throughput: {t.median_change_pct:+.1f}%  ·  "
                      f"{'confidence intervals separated' if c.separated else 'confidence intervals OVERLAP'}")
    verdict = "[bold green]SLO RECOVERED[/bold green]" if report.slo_recovered else "[bold red]SLO NOT RECOVERED[/bold red]"
    console.print(f"{verdict} (whole 95% CI under target, tests passing)")


def _print_race(report: RaceReport) -> None:
    evaluation = report.evaluation
    table = Table(title=f"Candidate race · {evaluation.objective.endpoint} {evaluation.objective.metric} < "
                        f"{evaluation.objective.target:g}")
    for column in ("", "tests", "runs", "median p99 ms", "Δ p99", "median rps", "Δ rps", "status"):
        table.add_column(column, justify="right" if column else "left")
    base = report.baseline
    if base.primary:
        tests = f"{base.tests.passed}/{base.tests.total}" if base.tests else "-"
        table.add_row("baseline", tests, str(len(base.primary_runs)), f"{base.median_load('p99_ms'):.1f}", "",
                      f"{base.median_load('throughput_rps'):.1f}", "", "")
    styles = {"winner": "bold green", "valid": "yellow", "rejected": "bold red"}
    for c in evaluation.candidates:
        status = c.status.upper()
        if c.name == evaluation.fastest_rejected:
            status = "FASTEST · REJECTED"
        table.add_row(
            c.name,
            f"{c.tests_passed}/{c.tests_total}" if c.tests_total else "-",
            str(c.runs),
            f"{c.p99_ms:.1f}" if c.p99_ms is not None else "-",
            f"{c.p99_change_pct:+.0f}%" if c.p99_change_pct is not None else "",
            f"{c.throughput_rps:.1f}" if c.throughput_rps is not None else "-",
            f"{c.throughput_change_pct:+.0f}%" if c.throughput_change_pct is not None else "",
            f"[{styles[c.status]}]{status}[/{styles[c.status]}]",
        )
    console.print(table)
    for c in evaluation.candidates:
        for reason in c.reasons:
            console.print(f"  [red]✗ {c.name}[/red]: {reason}")
        for test in c.failing_tests[:3]:
            console.print(f"      [dim]{test}[/dim]")
    if evaluation.winner:
        verdict = "[bold green]SLO RECOVERED[/bold green]" if evaluation.slo_recovered else "[yellow]SLO still violated[/yellow]"
        console.print(f"winner: [bold]{evaluation.winner}[/bold]  {verdict}")
    else:
        console.print("[bold red]no valid candidate improved on the baseline[/bold red]")


def _print_result(result: BenchmarkResult) -> None:
    if result.error:
        console.print(f"[bold red]ERROR[/bold red] {result.error}")
    if result.tests:
        t = result.tests
        style = "green" if t.ok else "red"
        console.print(f"tests [{style}]{t.passed}/{t.total} passed[/{style}]")
        for failure in t.failures:
            console.print(f"  [red]✗[/red] {failure.name}")
            console.print(f"    [dim]{failure.message}[/dim]")

    if result.runs:
        table = Table(title=f"{result.service} · {result.label}")
        for column in ("concurrency", "rps", "p50 ms", "p95 ms", "p99 ms", "errors", "app cpu", "app mem MB"):
            table.add_column(column, justify="right")
        for run in result.runs:
            load, app_usage = run.load, run.containers.get("app")
            table.add_row(
                str(load.concurrency),
                f"{load.throughput_rps:.1f}",
                f"{load.p50_ms:.1f}",
                f"{load.p95_ms:.1f}",
                f"{load.p99_ms:.1f}",
                f"{load.error_rate:.2%}",
                f"{app_usage.cpu_percent_avg:.0f}%" if app_usage else "-",
                f"{app_usage.memory_mb_max:.0f}" if app_usage else "-",
            )
        console.print(table)

    if result.slo_met is not None:
        objective = result.objective
        verdict = "[bold green]SLO MET[/bold green]" if result.slo_met else "[bold red]SLO VIOLATED[/bold red]"
        actual = getattr(result.primary.load, objective.metric)
        console.print(f"{verdict}  {objective.endpoint} {objective.metric} {actual:.1f} (target < {objective.target:g})")


if __name__ == "__main__":
    app()
