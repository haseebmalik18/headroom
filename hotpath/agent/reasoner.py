"""NVIDIA Nemotron as HotPath's reasoner (via Nebius Token Factory)."""

from pydantic import BaseModel, Field

from hotpath.agent import prompts
from hotpath.agent.investigator import Context, NotebookEntry
from hotpath.agent.schemas import ExperimentConclusion, Hypothesis, PatchCandidate
from hotpath.config import load_config
from hotpath.execution.worktrees import FileChange
from hotpath.models.nemotron import NemotronClient


class HypothesisSet(BaseModel):
    hypotheses: list[Hypothesis] = Field(min_length=1)


class ProposedFix(BaseModel):
    name: str
    strategy: str
    expected_effect: str
    risks: str = ""
    changes: list[FileChange] = Field(min_length=1)


class CandidateSet(BaseModel):
    candidates: list[ProposedFix] = Field(min_length=1)


def render_baseline(context: Context) -> str:
    base = context.baseline
    objective = base.objective
    lines = [
        "## Objective",
        f"{objective.endpoint}: {objective.metric} must be below {objective.target:g} ms.",
        "",
        "## Baseline measurement (production-like load test)",
    ]
    for run in base.runs:
        load = run.load
        lines.append(
            f"- {load.concurrency} concurrent users (think time {load.think_ms:g} ms): p50 {load.p50_ms:.1f} ms, "
            f"p95 {load.p95_ms:.1f} ms, p99 {load.p99_ms:.1f} ms, {load.throughput_rps:.1f} req/s, "
            f"errors {load.error_rate:.2%}"
        )
        if run.containers:
            lines.append("  containers: " + "; ".join(
                f"{name} CPU {u.cpu_percent_avg:.0f}% memory {u.memory_mb_max:.0f} MB" for name, u in run.containers.items()
            ))
    if base.tests:
        lines.append(f"- tests: {base.tests.passed}/{base.tests.total} passing")
    return "\n".join(lines)


def render_notebook(context: Context) -> str:
    if not context.notebook:
        return ""
    lines = ["## Lab notebook (earlier hypotheses and what the experiments showed)"]
    for entry in context.notebook:
        h, c = entry.hypothesis, entry.conclusion
        verdict = f"{c.verdict.upper()} ({c.confidence:.0%})" if c else "not yet concluded"
        lines.append(f"### {h.id}: {h.title} -> {verdict}")
        if entry.experiment:
            lines.append(entry.experiment.render())
        if c:
            lines += [f"- {o}" for o in c.key_observations]
    return "\n".join(lines)


def render_context(context: Context, include_code: bool = True) -> str:
    parts = [render_baseline(context)]
    if include_code:
        parts.append(context.repo_map.render())
    notebook = render_notebook(context)
    if notebook:
        parts.append(notebook)
    return "\n\n".join(parts)


def render_previous_races(context: Context) -> str:
    if not context.races:
        return ""
    lines = ["", "## Earlier candidate fixes and how they did (do not repeat failed approaches)"]
    for report in context.races:
        for c in report.evaluation.candidates:
            run = next(r for r in report.runs if r.candidate.name == c.name)
            outcome = f"{c.status}; p99 {c.p99_ms:.0f} ms" if c.p99_ms is not None else c.status
            lines.append(f"- {c.name} ({run.candidate.strategy}): {outcome}")
            lines += [f"  - rejected: {reason}" for reason in c.reasons]
            lines += [f"  - failing test: {t}" for t in c.failing_tests[:5]]
    return "\n".join(lines) + "\n"


class NemotronReasoner:
    def __init__(self, client: NemotronClient, repo):
        self.client = client
        self.config = load_config(repo)

    async def form_hypotheses(self, context: Context, limit: int) -> list[Hypothesis]:
        result = await self.client.complete_json(
            task="form_hypotheses",
            system=prompts.SYSTEM,
            user=prompts.FORM_HYPOTHESES.format(
                context=render_context(context), instruments=prompts.INSTRUMENTS, limit=min(limit, 3)
            ),
            schema=HypothesisSet,
        )
        return result.hypotheses

    async def conclude(self, context: Context, entry: NotebookEntry) -> ExperimentConclusion:
        h, plan = entry.hypothesis, entry.hypothesis.proposed_experiment
        predictions = "\n".join(
            f"- {p.observation}: if supported -> {p.if_supported}; if refuted -> {p.if_refuted}"
            for p in plan.predictions
        )
        earlier = context.model_copy(update={"notebook": [e for e in context.notebook if e is not entry]})
        conclusion = await self.client.complete_json(
            task="conclude",
            system=prompts.SYSTEM,
            user=prompts.CONCLUDE.format(
                context=render_context(earlier, include_code=False),
                hypothesis_id=h.id, title=h.title, explanation=h.explanation,
                rationale=plan.rationale, predictions=predictions, results=entry.experiment.render(),
            ),
            schema=ExperimentConclusion,
            temperature=0.0,
        )
        return conclusion.model_copy(update={"hypothesis_id": h.id})

    async def generate_candidates(self, context: Context, count: int) -> list[PatchCandidate]:
        root = context.root_cause
        result = await self.client.complete_json(
            task="generate_candidates",
            system=prompts.SYSTEM,
            user=prompts.GENERATE_CANDIDATES.format(
                context=render_context(context),
                title=root.hypothesis.title,
                explanation=root.hypothesis.explanation,
                observations="\n".join(f"- {o}" for o in root.conclusion.key_observations),
                tests="\n".join(f"- {t}" for t in context.repo_map.tests),
                protected="\n".join(f"- {p}" for p in self.config.runtime.protected_paths),
                previous=render_previous_races(context),
                count=count,
            ),
            schema=CandidateSet,
            temperature=0.4,
            max_tokens=16384,
        )
        return [PatchCandidate(**fix.model_dump()) for fix in result.candidates[:count]]
