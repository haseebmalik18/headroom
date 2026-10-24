from pathlib import Path

from hotpath.agent.investigator import Context, NotebookEntry, Outcome
from hotpath.agent.schemas import ExperimentConclusion, ExperimentPlan, Hypothesis, Prediction
from hotpath.agent.state import Phase
from hotpath.config import load_config
from hotpath.evals import REFERENCE_DIR, load_scenarios, score_outcome
from test_investigator import bench
from hotpath.repository.analyzer import RepositoryMap
from hotpath.config import Objective

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_scenarios_have_repos_and_reference_patches(monkeypatch):
    monkeypatch.chdir(ROOT)
    scenarios = load_scenarios()

    assert [s.name for s in scenarios] == ["lock-contention", "n-plus-one", "blocking-event-loop", "sequential-queries",
                                          "cache-stampede"]
    for s in scenarios:
        service = load_config(s.repo).service
        for fix in s.reference_fixes:
            assert (REFERENCE_DIR / service / f"{fix.name}.diff").exists(), f"{s.name}: missing {fix.name}.diff"
        assert any(f.expect == "valid" for f in s.reference_fixes)
        assert any(f.expect == "rejected" for f in s.reference_fixes)


def _outcome(title: str, explanation: str) -> Outcome:
    plan = ExperimentPlan(rationale="r", concurrency_levels=[10], measurements=["app_spans"],
                          predictions=[Prediction(observation="o", if_supported="s", if_refuted="r")])
    h = Hypothesis(id="H1", title=title, explanation=explanation, confidence=0.9, supporting_evidence=[],
                   contradicting_evidence=[], missing_evidence=[], proposed_experiment=plan)
    entry = NotebookEntry(hypothesis=h, conclusion=ExperimentConclusion(
        hypothesis_id="H1", verdict="supported", confidence=0.9, key_observations=[], explanation=""))
    objective = Objective(endpoint="GET /x", target=50)
    context = Context(repo_map=RepositoryMap(service="s", objective=objective, tree=[], dependencies=[],
                                             entrypoints=[], tests=[], relevant_files=[]),
                      baseline=bench("baseline", [100]), notebook=[entry], root_cause=entry)
    return Outcome(phase=Phase.UNRESOLVED, context=context)


def test_score_matches_root_cause_keywords(monkeypatch):
    monkeypatch.chdir(ROOT)
    n_plus_one = next(s for s in load_scenarios() if s.name == "n-plus-one")

    hit = score_outcome(n_plus_one, _outcome("N+1 query pattern", "Two queries are issued for each product."))
    miss = score_outcome(n_plus_one, _outcome("Database CPU saturation", "Postgres is overloaded."))

    assert hit.root_cause_identified and not miss.root_cause_identified
    assert hit.valid_fix_generated is False and hit.slo_recovered is False
