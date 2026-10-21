"""The real lab: everything the investigator executes, run locally with Docker Compose."""

from collections.abc import Callable
from pathlib import Path

from hotpath.agent.experiments import ExperimentResult, run_experiment
from hotpath.agent.schemas import ExperimentPlan, PatchCandidate
from hotpath.benchmark.race import RaceReport, race
from hotpath.benchmark.results import BenchmarkResult
from hotpath.benchmark.runner import run_benchmark
from hotpath.benchmark.verify import VerificationReport, build_report
from hotpath.config import load_config
from hotpath.execution.backend import ExecutionBackend, LocalExecutionBackend
from hotpath.repository.analyzer import RepositoryMap, analyze


class LocalLab:
    def __init__(
        self,
        repo: Path,
        *,
        warmup: str = "5s",
        duration: str = "20s",
        race_repeats: int = 3,
        verify_runs: int = 7,
        backend: ExecutionBackend | None = None,
        log: Callable[[str], None] = lambda _: None,
    ):
        self.repo = Path(repo).resolve()
        self.config = load_config(self.repo)
        self.workload = self.config.workload.model_copy(update={"warmup": warmup, "duration": duration})
        self.warmup, self.duration = warmup, duration
        self.race_repeats = race_repeats
        self.verify_runs = verify_runs
        self.backend = backend or LocalExecutionBackend(self.repo, log=log)
        self.log = log

    def analyze(self) -> RepositoryMap:
        return analyze(self.repo)

    async def baseline(self) -> BenchmarkResult:
        return await run_benchmark(self.repo, label="baseline", workloads=[self.workload] * self.race_repeats,
                                   log=lambda m: self.log(f"[baseline] {m}"))

    async def experiment(self, plan: ExperimentPlan) -> ExperimentResult:
        return await run_experiment(self.repo, plan, warmup=self.warmup, duration=self.duration,
                                    log=lambda m: self.log(f"[experiment] {m}"))

    async def race(self, candidates: list[PatchCandidate], baseline: BenchmarkResult) -> RaceReport:
        return await race(self.repo, candidates, self.backend, workloads=[self.workload] * self.race_repeats,
                          baseline=baseline, log=self.log)

    async def verify(self, report: RaceReport) -> VerificationReport:
        winner = next(r for r in report.runs if r.candidate.name == report.evaluation.winner)
        workloads = [self.workload] * self.verify_runs
        baseline = await run_benchmark(self.repo, label="verify-baseline", workloads=workloads,
                                       run_tests=False, log=lambda m: self.log(f"[verify baseline] {m}"))
        candidate = (await self.backend.evaluate_candidate(winner.candidate, workloads)).result
        return build_report(candidate, self.config.objective, baseline)
