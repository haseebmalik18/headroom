"""Observable investigation state.

The investigator is an explicit state machine. Every transition and every
artifact (hypothesis, experiment, conclusion, race, verification) is appended to
an event log that the CLI prints and the dashboard renders.
"""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Phase(StrEnum):
    ANALYZE_REPOSITORY = "analyze_repository"
    BASELINE = "baseline"
    FORM_HYPOTHESIS = "form_hypothesis"
    RUN_EXPERIMENT = "run_experiment"
    EVALUATE_EVIDENCE = "evaluate_evidence"
    ROOT_CAUSE_SUPPORTED = "root_cause_supported"
    GENERATE_CANDIDATES = "generate_candidates"
    EVALUATE_CANDIDATES = "evaluate_candidates"
    VERIFY_WINNER = "verify_winner"
    AWAITING_APPROVAL = "awaiting_approval"
    SLO_ALREADY_MET = "slo_already_met"
    UNRESOLVED = "unresolved"


TERMINAL = {Phase.AWAITING_APPROVAL, Phase.SLO_ALREADY_MET, Phase.UNRESOLVED}


class Budget(BaseModel):
    max_hypotheses: int = 4
    max_experiments: int = 5
    max_patch_rounds: int = 3
    candidates_per_round: int = 3


class Event(BaseModel):
    at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    phase: Phase
    kind: str            # e.g. "phase", "hypothesis", "experiment", "conclusion", "race", "verification", "note"
    message: str
    data: dict[str, Any] = {}
