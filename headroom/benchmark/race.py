"""Candidate race: benchmark the baseline and every candidate, then let the evaluator pick."""

import asyncio
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from headroom.agent.schemas import PatchCandidate
from headroom.benchmark.evaluator import Evaluation, evaluate
from headroom.benchmark.results import BenchmarkResult
from headroom.benchmark.runner import run_benchmark
from headroom.config import Workload, load_config
from headroom.execution.backend import CandidateRun, ExecutionBackend


class RaceReport(BaseModel):
    baseline: BenchmarkResult
    runs: list[CandidateRun]
    evaluation: Evaluation


async def race(
    repo: Path,
    candidates: list[PatchCandidate],
    backend: ExecutionBackend,
    *,
    workloads: list[Workload] | None = None,
    baseline: BenchmarkResult | None = None,
    parallel: int = 1,
    log: Callable[[str], None] = lambda _: None,
) -> RaceReport:
    config = load_config(repo)
    if baseline is None:
        log("benchmarking baseline")
        baseline = await run_benchmark(repo, label="baseline", workloads=workloads, out_dir=Path(".headroom/runs"),
                                       log=lambda msg: log(f"[baseline] {msg}"))

    # Benchmarks on one machine compete for CPU, so locally candidates run one at a
    # time by default; isolated cloud jobs can safely run in parallel.
    slots = asyncio.Semaphore(parallel)

    async def run(candidate: PatchCandidate) -> CandidateRun:
        async with slots:
            return await backend.evaluate_candidate(candidate, workloads)

    runs = list(await asyncio.gather(*(run(c) for c in candidates)))
    evaluation = evaluate(
        baseline,
        {r.candidate.name: r.result for r in runs},
        config.objective,
        config.constraints,
    )
    return RaceReport(baseline=baseline, runs=runs, evaluation=evaluation)
