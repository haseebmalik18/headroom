"""NemotronReasoner against a mocked Token Factory: prompts render and outputs parse."""

import json
from datetime import datetime, timezone
from pathlib import Path

import httpx

from hotpath.agent.experiments import ExperimentResult, LevelObservation
from hotpath.agent.investigator import Context, NotebookEntry
from hotpath.agent.reasoner import NemotronReasoner, render_previous_races
from hotpath.agent.schemas import ExperimentPlan, Hypothesis, PatchCandidate, Prediction
from hotpath.benchmark.evaluator import evaluate
from hotpath.benchmark.race import RaceReport
from hotpath.benchmark.results import BenchmarkResult, ContainerUsage, LoadReport, LoadRun, TestReport
from hotpath.benchmark.verify import build_report
from hotpath.config import Constraints, Objective
from hotpath.execution.backend import CandidateRun
from hotpath.models.nemotron import NemotronClient
from hotpath.repository.analyzer import analyze

CHECKOUT = Path(__file__).resolve().parents[1] / "examples" / "checkout-service"
PLAN = {
    "rationale": "Database saturation would show many active connections and high DB CPU.",
    "concurrency_levels": [100, 500],
    "measurements": ["db_activity", "container_resources"],
    "predictions": [{"observation": "db active connections at 500", "if_supported": "near pool size (20)",
                     "if_refuted": "about 1"}],
}
HYPOTHESIS = {"id": "H1", "title": "Database write contention", "explanation": "Writes queue in PostgreSQL.",
              "confidence": 0.58, "supporting_evidence": ["p99 grows with load"], "contradicting_evidence": [],
              "missing_evidence": ["DB-side activity"], "proposed_experiment": PLAN}


def _context() -> Context:
    now = datetime.now(timezone.utc)
    load = LoadReport(label="l", vus=500, think_ms=2000, duration_s=20, requests=100, p50_ms=3600, p95_ms=3800,
                      p99_ms=3850, max_ms=3900, avg_ms=3600, throughput_rps=88, error_rate=0.0)
    baseline = BenchmarkResult(
        service="checkout-service", label="baseline", repo=str(CHECKOUT), started_at=now, finished_at=now,
        objective=Objective(endpoint="POST /inventory/reserve", target=100),
        tests=TestReport(total=17, passed=17, failed=0, errors=0, skipped=0, duration_s=1, failures=[]),
        runs=[LoadRun(load=load, containers={"app": ContainerUsage(cpu_percent_avg=35, cpu_percent_max=40,
                                                                  memory_mb_max=70, samples=3)})],
    )
    return Context(repo_map=analyze(CHECKOUT), baseline=baseline)


def _run(p99: float) -> LoadRun:
    return LoadRun(load=LoadReport(label="l", vus=500, think_ms=2000, duration_s=20, requests=100, p50_ms=p99,
                                   p95_ms=p99, p99_ms=p99, max_ms=p99, avg_ms=p99, throughput_rps=250,
                                   error_rate=0.0))


def _reasoner(reply: dict, seen: list) -> NemotronReasoner:
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(reply)}}], "usage": {}})

    client = NemotronClient(api_key="k", model="nvidia/nemotron-test", transport=httpx.MockTransport(handler))
    return NemotronReasoner(client, CHECKOUT)


async def test_form_hypotheses_prompt_contains_evidence_and_code():
    seen = []
    hypotheses = await _reasoner({"hypotheses": [HYPOTHESIS]}, seen).form_hypotheses(_context(), limit=3)

    assert hypotheses[0].title == "Database write contention"
    prompt = seen[0]["messages"][1]["content"]
    assert "p99 3850.0 ms" in prompt
    assert "async def reserve(" in prompt
    assert "db_activity" in prompt
    assert "inventory.lock_wait" not in prompt.split("## app/main.py")[0]  # spans are not in the alert evidence


async def test_conclude_sees_measurements_and_keeps_hypothesis_id():
    context = _context()
    entry = NotebookEntry(
        hypothesis=Hypothesis.model_validate(HYPOTHESIS),
        experiment=ExperimentResult(plan=ExperimentPlan.model_validate(PLAN), levels=[
            LevelObservation(concurrency=500, p50_ms=3600, p95_ms=3800, p99_ms=3850, throughput_rps=88, error_rate=0)
        ]),
    )
    context.notebook.append(entry)
    seen = []
    reply = {"hypothesis_id": "wrong", "verdict": "disproved", "confidence": 0.9,
             "key_observations": ["db active connections avg 1.0 of 5"], "explanation": "DB mostly idle."}

    conclusion = await _reasoner(reply, seen).conclude(context, entry)

    assert conclusion.hypothesis_id == "H1"
    assert conclusion.verdict == "disproved"
    prompt = seen[0]["messages"][1]["content"]
    assert "500 | 3600.0 | 3850.0" in prompt
    assert "near pool size (20)" in prompt


async def test_generate_candidates_lists_protected_files_and_tests():
    context = _context()
    entry = NotebookEntry(hypothesis=Hypothesis.model_validate(HYPOTHESIS | {"id": "H2", "title": "Global lock"}))
    entry.conclusion = (await _reasoner({"hypothesis_id": "H2", "verdict": "supported", "confidence": 0.94,
                                         "key_observations": ["lock wait p99 3830 ms"], "explanation": "x"},
                                        []).conclude(context, NotebookEntry(
        hypothesis=entry.hypothesis, experiment=ExperimentResult(plan=ExperimentPlan.model_validate(PLAN), levels=[])
    )))
    context.root_cause = entry
    seen = []
    reply = {"candidates": [{"name": "per-sku-locks", "strategy": "Lock per SKU", "expected_effect": "parallel",
                             "risks": "hot SKUs still serialize",
                             "changes": [{"path": "app/inventory.py", "content": "# new\n"}]}]}

    candidates = await _reasoner(reply, seen).generate_candidates(context, count=3)

    assert candidates[0].name == "per-sku-locks"
    assert candidates[0].changes[0].path == "app/inventory.py"
    prompt = seen[0]["messages"][1]["content"]
    assert "tests/test_inventory_concurrency.py::test_concurrent_reservations_never_oversell" in prompt
    assert "- tests/*" in prompt
    assert "MATERIALLY DIFFERENT" in prompt
    assert "keep its existing function signatures" in prompt


def test_previous_races_explain_a_failed_verification():
    context = _context()
    candidate = PatchCandidate(name="row-locks", strategy="SELECT ... FOR UPDATE", expected_effect="parallel")
    result = context.baseline.model_copy(update={"label": "row-locks", "runs": [_run(14)]})
    evaluation = evaluate(context.baseline, {"row-locks": result}, context.baseline.objective, Constraints())
    context.races.append(RaceReport(baseline=context.baseline, evaluation=evaluation, runs=[
        CandidateRun(candidate=candidate, diff="d", changed_files=["app/inventory.py"], result=result)]))
    spiky = result.model_copy(update={"runs": [_run(p) for p in [14, 15, 14, 18, 114]]})
    context.verifications.append(build_report(spiky, context.baseline.objective, context.baseline))

    text = render_previous_races(context)

    assert "- row-locks (SELECT ... FOR UPDATE): winner; p99 14 ms" in text
    assert "per run 14, 15, 14, 18, 114 ms" in text
    assert "4 of 5 runs met the 100 ms target -> not verified" in text
