import asyncio
import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from hotpath.benchmark.results import BenchmarkResult
from hotpath.benchmark.runner import run_benchmark
from hotpath.config import load_config

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
