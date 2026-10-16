"""The HotPath investigation loop.

    analyze repository -> baseline -> confirm SLO violation
    -> form competing hypotheses -> for each: run its experiment, conclude
       (disproved -> next hypothesis; budget left and none supported -> revise)
    -> root cause supported -> generate materially different fixes
    -> race them (deterministic evaluator picks; all rejected -> analyze failures, retry)
    -> verify the winner with repeated runs -> await human approval

Nemotron (the Reasoner) reasons and writes code. The Lab executes and measures.
Only the evaluator and the verification statistics decide what worked.
"""

from collections.abc import Callable
from typing import Protocol

from pydantic import BaseModel

from hotpath.agent.experiments import ExperimentResult
from hotpath.agent.schemas import ExperimentConclusion, ExperimentPlan, Hypothesis, PatchCandidate
from hotpath.agent.state import Budget, Event, Phase
from hotpath.benchmark.race import RaceReport
from hotpath.benchmark.results import BenchmarkResult
from hotpath.benchmark.verify import VerificationReport
from hotpath.repository.analyzer import RepositoryMap

SUPPORT_THRESHOLD = 0.75


class NotebookEntry(BaseModel):
    hypothesis: Hypothesis
    experiment: ExperimentResult | None = None
    conclusion: ExperimentConclusion | None = None


class Context(BaseModel):
    """Everything the model is allowed to know at a given point."""

    repo_map: RepositoryMap
    baseline: BenchmarkResult
    notebook: list[NotebookEntry] = []
    root_cause: NotebookEntry | None = None
    races: list[RaceReport] = []


class Reasoner(Protocol):
    async def form_hypotheses(self, context: Context, limit: int) -> list[Hypothesis]: ...
    async def conclude(self, context: Context, entry: NotebookEntry) -> ExperimentConclusion: ...
    async def generate_candidates(self, context: Context, count: int) -> list[PatchCandidate]: ...


class Lab(Protocol):
    def analyze(self) -> RepositoryMap: ...
    async def baseline(self) -> BenchmarkResult: ...
    async def experiment(self, plan: ExperimentPlan) -> ExperimentResult: ...
    async def race(self, candidates: list[PatchCandidate], baseline: BenchmarkResult) -> RaceReport: ...
    async def verify(self, race: RaceReport) -> VerificationReport: ...


class Outcome(BaseModel):
    phase: Phase
    context: Context | None = None
    winner: str | None = None
    diff: str | None = None
    verification: VerificationReport | None = None
    reason: str | None = None


class Investigator:
    def __init__(self, reasoner: Reasoner, lab: Lab, budget: Budget | None = None,
                 on_event: Callable[[Event], None] = lambda _: None):
        self.reasoner = reasoner
        self.lab = lab
        self.budget = budget or Budget()
        self.on_event = on_event
        self.events: list[Event] = []

    def emit(self, phase: Phase, kind: str, message: str, **data) -> None:
        event = Event(phase=phase, kind=kind, message=message, data=data)
        self.events.append(event)
        self.on_event(event)

    async def run(self) -> Outcome:
        self.emit(Phase.ANALYZE_REPOSITORY, "phase", "Analyzing repository")
        repo_map = self.lab.analyze()
        self.emit(Phase.ANALYZE_REPOSITORY, "note",
                  f"Mapped {len(repo_map.tree)} files; {len(repo_map.relevant_files)} on the endpoint's code path",
                  relevant=[f.path for f in repo_map.relevant_files])

        self.emit(Phase.BASELINE, "phase", "Measuring baseline")
        baseline = await self.lab.baseline()
        if baseline.error:
            return self._finish(Phase.UNRESOLVED, None, reason=f"baseline failed: {baseline.error}")
        objective = baseline.objective
        actual = baseline.median_load(objective.metric)
        self.emit(Phase.BASELINE, "baseline",
                  f"{objective.endpoint} {objective.metric} {actual:.0f}ms (target < {objective.target:g}ms)",
                  summary=baseline.summary(), slo_met=baseline.slo_met)
        context = Context(repo_map=repo_map, baseline=baseline)
        if baseline.slo_met:
            return self._finish(Phase.SLO_ALREADY_MET, context, reason="baseline already meets the SLO")

        if not await self._find_root_cause(context):
            return self._finish(Phase.UNRESOLVED, context,
                                reason="investigation budget exhausted without a supported root cause")

        return await self._fix(context)

    async def _find_root_cause(self, context: Context) -> bool:
        hypotheses_used = experiments_run = 0
        while hypotheses_used < self.budget.max_hypotheses and experiments_run < self.budget.max_experiments:
            self.emit(Phase.FORM_HYPOTHESIS, "phase",
                      "Forming hypotheses" if not context.notebook else "Revising hypotheses with new evidence")
            limit = self.budget.max_hypotheses - hypotheses_used
            hypotheses = (await self.reasoner.form_hypotheses(context, limit))[:limit]
            if not hypotheses:
                return False
            hypotheses.sort(key=lambda h: -h.confidence)
            hypotheses_used += len(hypotheses)
            for h in hypotheses:
                self.emit(Phase.FORM_HYPOTHESIS, "hypothesis", f"{h.id}: {h.title}", hypothesis=h.model_dump())

            for h in hypotheses:
                if experiments_run >= self.budget.max_experiments:
                    break
                entry = NotebookEntry(hypothesis=h)
                context.notebook.append(entry)

                self.emit(Phase.RUN_EXPERIMENT, "phase", f"Testing {h.id}: {h.title}",
                          plan=h.proposed_experiment.model_dump())
                entry.experiment = await self.lab.experiment(h.proposed_experiment)
                experiments_run += 1
                self.emit(Phase.RUN_EXPERIMENT, "experiment", f"Experiment for {h.id} complete",
                          hypothesis_id=h.id, result=entry.experiment.model_dump())

                entry.conclusion = await self.reasoner.conclude(context, entry)
                c = entry.conclusion
                self.emit(Phase.EVALUATE_EVIDENCE, "conclusion",
                          f"{h.id} {c.verdict.upper()} (confidence {c.confidence:.0%})",
                          hypothesis_id=h.id, conclusion=c.model_dump())

                if c.verdict == "supported" and c.confidence >= SUPPORT_THRESHOLD:
                    context.root_cause = entry
                    self.emit(Phase.ROOT_CAUSE_SUPPORTED, "root_cause", f"Root cause: {h.title}",
                              hypothesis_id=h.id, confidence=c.confidence)
                    return True
        return False

    async def _fix(self, context: Context) -> Outcome:
        for round_ in range(1, self.budget.max_patch_rounds + 1):
            self.emit(Phase.GENERATE_CANDIDATES, "phase", f"Generating candidate fixes (round {round_})")
            candidates = await self.reasoner.generate_candidates(context, self.budget.candidates_per_round)
            for c in candidates:
                self.emit(Phase.GENERATE_CANDIDATES, "candidate", f"{c.name}: {c.strategy}",
                          candidate=c.model_dump(exclude={"changes", "patch"}),
                          files=[ch.path for ch in c.changes])

            self.emit(Phase.EVALUATE_CANDIDATES, "phase", f"Racing {len(candidates)} candidates")
            report = await self.lab.race(candidates, context.baseline)
            context.races.append(report)
            evaluation = report.evaluation
            self.emit(Phase.EVALUATE_CANDIDATES, "race",
                      f"Winner: {evaluation.winner}" if evaluation.winner else "No valid candidate",
                      evaluation=evaluation.model_dump())

            if evaluation.winner and evaluation.slo_recovered:
                self.emit(Phase.VERIFY_WINNER, "phase", f"Verifying {evaluation.winner} with repeated runs")
                verification = await self.lab.verify(report)
                self.emit(Phase.VERIFY_WINNER, "verification",
                          "SLO recovered" if verification.slo_recovered else "Verification did not hold up",
                          report=verification.model_dump())
                if verification.slo_recovered:
                    winner_run = next(r for r in report.runs if r.candidate.name == evaluation.winner)
                    return self._finish(Phase.AWAITING_APPROVAL, context, winner=evaluation.winner,
                                        diff=winner_run.diff, verification=verification)
        return self._finish(Phase.UNRESOLVED, context,
                            reason=f"no candidate recovered the SLO after {self.budget.max_patch_rounds} rounds")

    def _finish(self, phase: Phase, context: Context | None, **kwargs) -> Outcome:
        outcome = Outcome(phase=phase, context=context, **kwargs)
        message = {
            Phase.AWAITING_APPROVAL: "Verified patch ready: awaiting human approval",
            Phase.SLO_ALREADY_MET: "SLO already met: nothing to fix",
        }.get(phase, f"Unresolved: {kwargs.get('reason')}")
        self.emit(phase, "phase", message, winner=kwargs.get("winner"))
        return outcome
