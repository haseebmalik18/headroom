"""Structured artifacts exchanged between Nemotron and HotPath.

Anything the model produces that HotPath acts on is validated against one of
these schemas; nothing is scraped out of prose.
"""

from typing import Literal

from pydantic import BaseModel, Field

from hotpath.execution.worktrees import FileChange

Measurement = Literal["app_spans", "container_resources", "db_activity"]


class Prediction(BaseModel):
    observation: str = Field(description="The specific measurement to look at, e.g. 'db active connections at 500'")
    if_supported: str = Field(description="What that measurement shows if the hypothesis is true")
    if_refuted: str = Field(description="What it shows if the hypothesis is false")


class ExperimentPlan(BaseModel):
    rationale: str = Field(description="Why this experiment discriminates between the hypotheses")
    concurrency_levels: list[int] = Field(
        min_length=1, max_length=4, description="Load levels to run (concurrent users), e.g. [25, 100, 500]"
    )
    measurements: list[Measurement] = Field(
        description="Instruments to collect in addition to client latency/throughput: "
                    "app_spans (in-process timings), container_resources (CPU/memory per container), "
                    "db_activity (active DB connections, wait events, commit rate)"
    )
    predictions: list[Prediction] = Field(min_length=1)


class Hypothesis(BaseModel):
    id: str = Field(description="Short stable id, e.g. 'H1'")
    title: str
    explanation: str
    confidence: float = Field(ge=0, le=1)
    supporting_evidence: list[str]
    contradicting_evidence: list[str]
    missing_evidence: list[str]
    proposed_experiment: ExperimentPlan


class ExperimentConclusion(BaseModel):
    hypothesis_id: str
    verdict: Literal["supported", "disproved", "inconclusive"]
    confidence: float = Field(ge=0, le=1)
    key_observations: list[str] = Field(description="The measured facts that decided the verdict, with numbers")
    explanation: str


class PatchCandidate(BaseModel):
    name: str = Field(description="Short identifier, e.g. 'per-sku-locks'")
    strategy: str = Field(description="One sentence: what the fix changes")
    expected_effect: str = Field(description="What should happen to latency, throughput and correctness")
    risks: str = Field(default="", description="What could go wrong with this approach")
    changes: list[FileChange] = Field(
        default=[], description="Complete new contents of every file the fix modifies or creates"
    )
    patch: str | None = Field(default=None, description="Alternatively, a unified diff (used for hand-written patches)")
