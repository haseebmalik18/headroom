"""Evaluation across several performance-failure scenarios.

Reference mode proves each scenario is real and solvable without any model:
the baseline violates its SLO, hand-written correct fixes pass every test, and
hand-written broken fixes are rejected.

Agent mode runs the full investigation on each scenario and scores:
root cause identified, valid fix generated, SLO recovered (verified).
"""

import shutil
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic import BaseModel

from headroom.agent.investigator import Outcome
from headroom.agent.schemas import PatchCandidate
from headroom.agent.state import Phase
from headroom.benchmark.race import RaceReport, race
from headroom.config import CONFIG_FILE, Objective, load_config
from headroom.execution.backend import LocalExecutionBackend

MANIFEST = Path("evals/scenarios.yaml")
REFERENCE_DIR = Path("evals/reference")


class ReferenceFix(BaseModel):
    name: str
    expect: str  # "valid" | "rejected"


class Scenario(BaseModel):
    name: str
    repo: Path
    objective: dict | None = None   # run the repo under a different goal than its own headroom.yaml
    root_cause: str
    root_cause_keywords: list[str]
    reference_fixes: list[ReferenceFix] = []


def load_scenarios(manifest: Path = MANIFEST) -> list[Scenario]:
    return [Scenario.model_validate(s) for s in yaml.safe_load(manifest.read_text())["scenarios"]]


def prepare(scenario: Scenario, root: Path = Path(".headroom/scenarios")) -> Path:
    """The repository to run: the scenario's own, or a fresh copy with its objective replaced."""
    if not scenario.objective:
        return scenario.repo
    repo = Path(root) / scenario.name
    shutil.rmtree(repo, ignore_errors=True)
    shutil.copytree(scenario.repo, repo, ignore=shutil.ignore_patterns("results", "__pycache__", ".pytest_cache"))
    config = yaml.safe_load((repo / CONFIG_FILE).read_text())
    config["objective"] = Objective(**{**config["objective"], **scenario.objective}).model_dump()
    (repo / CONFIG_FILE).write_text(yaml.safe_dump(config, sort_keys=False))
    return repo


class ReferenceCheck(BaseModel):
    scenario: str
    baseline_violates_slo: bool
    fixes_as_expected: dict[str, bool]
    slo_recovered_by_reference: bool
    report: RaceReport

    @property
    def ok(self) -> bool:
        return self.baseline_violates_slo and all(self.fixes_as_expected.values()) and self.slo_recovered_by_reference


async def check_reference(scenario: Scenario, *, repeats: int = 3, warmup: str = "5s", duration: str = "20s",
                          log: Callable[[str], None] = lambda _: None) -> ReferenceCheck:
    repo = prepare(scenario)
    service = load_config(repo).service
    candidates = [
        PatchCandidate(name=fix.name, strategy="reference fix", expected_effect="",
                       patch=(REFERENCE_DIR / service / f"{fix.name}.diff").read_text())
        for fix in scenario.reference_fixes
    ]
    workload = load_config(repo).workload.model_copy(update={"warmup": warmup, "duration": duration})
    report = await race(repo, candidates, LocalExecutionBackend(repo, log=log),
                        workloads=[workload] * repeats, log=log)
    statuses = {c.name: c.status for c in report.evaluation.candidates}
    expected = {
        fix.name: (statuses[fix.name] == "rejected") == (fix.expect == "rejected")
        for fix in scenario.reference_fixes
    }
    return ReferenceCheck(
        scenario=scenario.name,
        baseline_violates_slo=report.baseline.slo_met is False,
        fixes_as_expected=expected,
        slo_recovered_by_reference=report.evaluation.slo_recovered,
        report=report,
    )


class AgentScore(BaseModel):
    scenario: str
    phase: Phase
    supported_hypothesis: str | None
    root_cause_identified: bool
    valid_fix_generated: bool
    slo_recovered: bool
    winner: str | None


def score_outcome(scenario: Scenario, outcome: Outcome) -> AgentScore:
    context = outcome.context
    root = context.root_cause if context else None
    text = f"{root.hypothesis.title} {root.hypothesis.explanation}".lower() if root else ""
    valid_fix = bool(context and any(r.evaluation.winner for r in context.races))
    return AgentScore(
        scenario=scenario.name,
        phase=outcome.phase,
        supported_hypothesis=root.hypothesis.title if root else None,
        root_cause_identified=any(k.lower() in text for k in scenario.root_cause_keywords),
        valid_fix_generated=valid_fix,
        slo_recovered=bool(outcome.verification and outcome.verification.slo_recovered),
        winner=outcome.winner,
    )
