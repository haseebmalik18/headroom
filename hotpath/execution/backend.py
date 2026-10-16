"""Where candidate patches get built, tested and benchmarked.

LocalExecutionBackend runs everything on this machine with Docker Compose.
A Nebius Serverless Jobs backend implements the same protocol.
"""

from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel

from hotpath.agent.schemas import PatchCandidate
from hotpath.benchmark.results import BenchmarkResult
from hotpath.benchmark.runner import run_benchmark
from hotpath.config import Workload, load_config
from hotpath.execution.worktrees import PatchError, Workspace


class CandidateRun(BaseModel):
    candidate: PatchCandidate
    diff: str
    changed_files: list[str]
    result: BenchmarkResult


class ExecutionBackend(Protocol):
    async def evaluate_candidate(
        self, candidate: PatchCandidate, workloads: list[Workload] | None = None
    ) -> CandidateRun: ...


class LocalExecutionBackend:
    def __init__(self, repo: Path, work_root: Path = Path(".hotpath"), log: Callable[[str], None] = lambda _: None):
        self.repo = Path(repo).resolve()
        self.work_root = Path(work_root).resolve()
        self.log = log

    async def evaluate_candidate(
        self, candidate: PatchCandidate, workloads: list[Workload] | None = None
    ) -> CandidateRun:
        workspace = Workspace.create(self.repo, self.work_root / "worktrees", candidate.name)
        try:
            try:
                if candidate.changes:
                    workspace.write_files(candidate.changes)
                if candidate.patch:
                    workspace.apply_patch(candidate.patch)
            except PatchError as exc:
                return CandidateRun(
                    candidate=candidate, diff="", changed_files=[],
                    result=_failed(self.repo, candidate.name, f"patch did not apply: {exc}"),
                )

            diff = workspace.diff()
            changed = workspace.changed_files()
            self.log(f"[{candidate.name}] patched {', '.join(changed) or 'nothing'}")
            result = await run_benchmark(
                workspace.path,
                label=candidate.name,
                workloads=workloads,
                out_dir=self.work_root / "runs",
                log=lambda msg: self.log(f"[{candidate.name}] {msg}"),
            )
            return CandidateRun(candidate=candidate, diff=diff, changed_files=changed, result=result)
        finally:
            workspace.destroy()


def _failed(repo: Path, label: str, error: str) -> BenchmarkResult:
    now = datetime.now(timezone.utc)
    return BenchmarkResult(
        service=load_config(repo).service, label=label, repo=str(repo),
        started_at=now, finished_at=now, objective=load_config(repo).objective, error=error,
    )
