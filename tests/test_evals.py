from pathlib import Path

from headroom.agent.investigator import Context, NotebookEntry, Outcome
from headroom.agent.schemas import ExperimentConclusion, ExperimentPlan, Hypothesis, Prediction
from headroom.agent.state import Phase
from headroom.config import load_config
from headroom.evals import REFERENCE_DIR, load_scenarios, prepare, score_outcome
from test_investigator import bench
from headroom.repository.analyzer import RepositoryMap
from headroom.config import Objective

ROOT = Path(__file__).resolve().parents[1]


def test_manifest_scenarios_have_repos_and_reference_patches(monkeypatch):
    monkeypatch.chdir(ROOT)
    scenarios = load_scenarios()

    assert [s.name for s in scenarios] == ["lock-contention", "n-plus-one", "blocking-event-loop", "sequential-queries",
                                          "cache-stampede", "checkout-throughput"]
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


def test_a_scenario_can_run_an_existing_service_under_a_different_goal(monkeypatch, tmp_path):
    monkeypatch.chdir(ROOT)
    scenario = next(s for s in load_scenarios() if s.name == "checkout-throughput")

    repo = prepare(scenario, root=tmp_path)

    goal = load_config(repo).objective
    assert (goal.metric, goal.target) == ("throughput_rps", 240)
    assert load_config(scenario.repo).objective.metric == "p99_ms"   # the original is untouched
    assert (repo / "app" / "inventory.py").read_text() == (scenario.repo / "app" / "inventory.py").read_text()
    assert not (repo / "results").exists()
