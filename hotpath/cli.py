import asyncio
import json
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from hotpath.agent.experiments import run_experiment
from hotpath.agent.schemas import ExperimentPlan, PatchCandidate, Prediction
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


@app.command("investigate")
def investigate_command(
    repo: Annotated[Path, typer.Argument(help="Repository containing hotpath.yaml")],
    model: Annotated[Optional[str], typer.Option(help="Nemotron model id on Token Factory (default: NEMOTRON_MODEL)")] = None,
    warmup: Annotated[str, typer.Option(help="Warmup before each measured run")] = "5s",
    duration: Annotated[str, typer.Option(help="Measured duration of each run")] = "20s",
    race_repeats: Annotated[int, typer.Option(help="Load runs per candidate in the race")] = 3,
    verify_runs: Annotated[int, typer.Option(help="Repeated runs when verifying the winner (7+ so a single outlier run cannot decide)")] = 7,
    max_hypotheses: Annotated[int, typer.Option()] = 4,
    max_experiments: Annotated[int, typer.Option()] = 5,
    max_patch_rounds: Annotated[int, typer.Option()] = 3,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show low-level execution logs")] = False,
) -> None:
    """Investigate an SLO violation end to end and stop at a verified patch awaiting approval."""
    from hotpath.agent.investigator import Investigator
    from hotpath.agent.lab import LocalLab
    from hotpath.agent.reasoner import NemotronReasoner
    from hotpath.agent.state import Budget, Phase
    from hotpath.agent.store import InvestigationStore
    from hotpath.models.nemotron import NemotronClient

    try:
        client = NemotronClient(model=model)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(2)
    if not client.model:
        console.print("[red]No model selected:[/red] set NEMOTRON_MODEL in .env or pass --model (see `hotpath models`)")
        raise typer.Exit(2)
    store = InvestigationStore.create(repo)
    log = (lambda msg: console.print(f"  [dim]{msg}[/dim]")) if verbose else (lambda _: None)
    lab = LocalLab(repo, warmup=warmup, duration=duration, race_repeats=race_repeats, verify_runs=verify_runs, log=log)

    def on_event(event):
        store.record(event)
        print_event(event)

    console.print(f"[bold]HotPath[/bold] · reasoning with [bold]{client.model}[/bold] via Nebius Token Factory")
    investigator = Investigator(
        NemotronReasoner(client, repo), lab,
        Budget(max_hypotheses=max_hypotheses, max_experiments=max_experiments, max_patch_rounds=max_patch_rounds),
        on_event=on_event,
    )
    outcome = asyncio.run(investigator.run())
    store.save_outcome(outcome, client.calls)
    tokens = sum(c.prompt_tokens + c.completion_tokens for c in client.calls)
    console.print(f"[dim]{len(client.calls)} Nemotron calls, {tokens:,} tokens · saved to {store.path}[/dim]")
    if outcome.diff:
        console.print(f"Review with [bold]hotpath show {store.path.name}[/bold], "
                      f"apply with [bold]hotpath approve {store.path.name}[/bold]")
    if outcome.phase == Phase.UNRESOLVED:
        raise typer.Exit(1)


@app.command("approve")
def approve_command(
    investigation: Annotated[str, typer.Argument(help="Investigation id, path, or 'latest'")] = "latest",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Apply without asking")] = False,
) -> None:
    """Human approval: show the verified diff and apply it to the real repository."""
    from hotpath.agent.state import Phase
    from hotpath.agent.store import InvestigationStore, apply_to_repository

    store = InvestigationStore.open(investigation)
    outcome = store.outcome()
    if outcome.phase != Phase.AWAITING_APPROVAL or not outcome.diff:
        console.print(f"[red]Nothing to approve:[/red] investigation ended in {outcome.phase.value}")
        raise typer.Exit(1)
    console.print(outcome.diff, markup=False, highlight=False)
    if not yes and not typer.confirm(f"Apply {outcome.winner} to {store.repo}?"):
        raise typer.Exit(1)
    changed = apply_to_repository(store.repo, outcome.diff)
    console.print(f"[green]Applied[/green] {outcome.winner}: {', '.join(changed)}")


def print_event(event) -> None:
    kind, data = event.kind, event.data
    if kind == "phase":
        console.print(f"\n[bold cyan]▶ {event.message}[/bold cyan]")
    elif kind == "baseline":
        verdict = "[green]SLO MET[/green]" if data.get("slo_met") else "[bold red]SLO VIOLATED[/bold red]"
        console.print(f"  {event.message}  {verdict}")
    elif kind == "hypothesis":
        h = data["hypothesis"]
        console.print(f"  [bold]Hypothesis {h['id']}[/bold] {h['title']}  [dim](confidence {h['confidence']:.0%})[/dim]")
    elif kind == "experiment":
        console.print(f"  [dim]{event.message}[/dim]")
    elif kind == "conclusion":
        c = data["conclusion"]
        style = {"supported": "green", "disproved": "red"}.get(c["verdict"], "yellow")
        console.print(f"  [bold {style}]{event.message}[/bold {style}]")
        for obs in c["key_observations"]:
            console.print(f"    · {obs}")
    elif kind == "root_cause":
        console.print(f"  [bold green]✓ {event.message}[/bold green]")
    elif kind == "candidate":
        console.print(f"  {event.message}")
    elif kind == "race":
        ev = data["evaluation"]
        for c in ev["candidates"]:
            p99 = f"{c['p99_ms']:.0f}ms" if c["p99_ms"] is not None else "-"
            tests = f"{c['tests_passed']}/{c['tests_total']}" if c["tests_total"] else "-"
            label = c["status"].upper()
            if c["name"] == ev["fastest_rejected"]:
                label = "FASTEST · REJECTED"
            style = {"winner": "bold green", "valid": "yellow", "rejected": "bold red"}[c["status"]]
            console.print(f"  {c['name']:<24} tests {tests:<6} p99 {p99:<8} [{style}]{label}[/{style}]")
            for reason in c["reasons"]:
                console.print(f"    [red]{reason}[/red]")
    elif kind == "verification":
        r = data["report"]
        cand, base = r["candidate"]["metric"], (r["baseline"] or {}).get("metric")
        if base:
            console.print(f"  baseline median {base['median']:.0f}ms (95% CI {base['ci_low']:.0f}–{base['ci_high']:.0f})")
        console.print(f"  patched  median {cand['median']:.0f}ms (95% CI {cand['ci_low']:.0f}–{cand['ci_high']:.0f}) "
                      f"over {r['candidate']['runs']} runs")
        style = "bold green" if r["slo_recovered"] else "bold red"
        console.print(f"  [{style}]{event.message}[/{style}]")
    else:
        console.print(f"  [dim]{event.message}[/dim]")


@app.command("show")
def show_command(
    investigation: Annotated[str, typer.Argument(help="Investigation id, path, or 'latest'")] = "latest",
) -> None:
    """Replay an investigation's timeline and show its verified diff."""
    from hotpath.agent.store import InvestigationStore

    store = InvestigationStore.open(investigation)
    for event in store.events():
        print_event(event)
    if (store.path / "outcome.json").exists() and store.outcome().diff:
        console.print("\n[bold]Verified diff[/bold]")
        console.print(store.outcome().diff, markup=False, highlight=False)


@app.command("eval")
def eval_command(
    reference: Annotated[bool, typer.Option(help="Validate scenarios with hand-written reference fixes (no model)")] = False,
    scenario: Annotated[Optional[list[str]], typer.Option(help="Only these scenarios (repeatable)")] = None,
    repeats: Annotated[int, typer.Option(help="Load runs per candidate")] = 3,
    verify_runs: Annotated[int, typer.Option(help="Verification runs (agent mode)")] = 7,
    model: Annotated[Optional[str], typer.Option(help="Nemotron model id (agent mode)")] = None,
) -> None:
    """Run every evaluation scenario and print a scorecard."""
    from datetime import datetime, timezone

    from hotpath.evals import check_reference, load_scenarios, score_outcome

    scenarios = [s for s in load_scenarios() if not scenario or s.name in scenario]
    out_dir = Path("evals/results")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    log = lambda msg: console.print(f"[dim]›[/dim] {msg}")  # noqa: E731

    if reference:
        table = Table(title="Reference validation (no model)")
        for column in ("scenario", "baseline violates SLO", "fixes behave as expected", "SLO recoverable", "winner"):
            table.add_column(column)
        checks = []
        for s in scenarios:
            console.print(f"\n[bold]{s.name}[/bold] ({s.repo})")
            check = asyncio.run(check_reference(s, repeats=repeats, log=log))
            checks.append(check)
            _print_race(check.report)
            mark = lambda ok: "[green]✓[/green]" if ok else "[red]✗[/red]"  # noqa: E731
            table.add_row(s.name, mark(check.baseline_violates_slo),
                          " ".join(f"{name} {mark(ok)}" for name, ok in check.fixes_as_expected.items()),
                          mark(check.slo_recovered_by_reference), check.report.evaluation.winner or "-")
        console.print(table)
        (out_dir / f"reference-{stamp}.json").write_text(
            "[" + ",".join(c.model_dump_json() for c in checks) + "]")
        raise typer.Exit(0 if all(c.ok for c in checks) else 1)

    from hotpath.agent.investigator import Investigator
    from hotpath.agent.lab import LocalLab
    from hotpath.agent.reasoner import NemotronReasoner
    from hotpath.agent.store import InvestigationStore
    from hotpath.models.nemotron import NemotronClient

    scores = []
    for s in scenarios:
        console.print(f"\n[bold]{s.name}[/bold] ({s.repo})")
        client = NemotronClient(model=model)
        store = InvestigationStore.create(s.repo)

        def on_event(event, store=store):
            store.record(event)
            print_event(event)

        investigator = Investigator(NemotronReasoner(client, s.repo),
                                    LocalLab(s.repo, race_repeats=repeats, verify_runs=verify_runs), on_event=on_event)
        outcome = asyncio.run(investigator.run())
        store.save_outcome(outcome, client.calls)
        scores.append(score_outcome(s, outcome))

    table = Table(title="HotPath evaluation")
    for column in ("scenario", "root cause identified", "valid fix", "SLO recovered", "supported hypothesis"):
        table.add_column(column)
    mark = lambda ok: "[green]✓[/green]" if ok else "[red]✗[/red]"  # noqa: E731
    for sc in scores:
        table.add_row(sc.scenario, mark(sc.root_cause_identified), mark(sc.valid_fix_generated),
                      mark(sc.slo_recovered), sc.supported_hypothesis or "-")
    console.print(table)
    console.print(f"root cause {sum(s.root_cause_identified for s in scores)}/{len(scores)} · "
                  f"valid fix {sum(s.valid_fix_generated for s in scores)}/{len(scores)} · "
                  f"SLO recovered {sum(s.slo_recovered for s in scores)}/{len(scores)}")
    (out_dir / f"agent-{stamp}.json").write_text("[" + ",".join(s.model_dump_json() for s in scores) + "]")


@app.command("models")
def models_command() -> None:
    """List the models your Nebius Token Factory key can use (Nemotron first)."""
    from hotpath.models.nemotron import NemotronClient

    models = asyncio.run(NemotronClient(model="-").list_models())
    for name in sorted(models, key=lambda m: ("nemotron" not in m.lower(), m)):
        style = "bold green" if "nemotron" in name.lower() else "dim"
        console.print(f"[{style}]{name}[/{style}]")


@app.command("experiment")
def experiment_command(
    repo: Annotated[Path, typer.Argument(help="Repository containing hotpath.yaml")],
    concurrency: Annotated[str, typer.Option(help="Concurrency levels, comma-separated")] = "100,500",
    measure: Annotated[
        str, typer.Option(help="Instruments: app_spans,container_resources,db_activity")
    ] = "container_resources,db_activity",
    warmup: Annotated[str, typer.Option(help="Warmup before measuring")] = "5s",
    duration: Annotated[str, typer.Option(help="Measured duration per level")] = "20s",
) -> None:
    """Run a hand-written experiment plan and print the evidence exactly as the model would see it."""
    plan = ExperimentPlan(
        rationale="manual experiment",
        concurrency_levels=[int(c) for c in concurrency.split(",")],
        measurements=[m.strip() for m in measure.split(",") if m.strip()],
        predictions=[Prediction(observation="manual", if_supported="-", if_refuted="-")],
    )
    log = lambda msg: console.print(f"[dim]›[/dim] {msg}")  # noqa: E731
    result = asyncio.run(run_experiment(repo, plan, warmup=warmup, duration=duration, log=log))
    console.print(result.render())


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
