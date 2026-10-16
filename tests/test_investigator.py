from datetime import datetime, timezone

from hotpath.agent.experiments import ExperimentResult
from hotpath.agent.investigator import Investigator
from hotpath.agent.schemas import ExperimentConclusion, ExperimentPlan, Hypothesis, PatchCandidate, Prediction
from hotpath.agent.state import Budget, Phase
from hotpath.benchmark.evaluator import evaluate
from hotpath.benchmark.race import RaceReport
from hotpath.benchmark.results import BenchmarkResult, LoadReport, LoadRun, TestReport
from hotpath.benchmark.verify import build_report
from hotpath.config import Constraints, Objective
from hotpath.execution.backend import CandidateRun
from hotpath.repository.analyzer import RepositoryMap

OBJECTIVE = Objective(endpoint="POST /inventory/reserve", metric="p99_ms", target=100)


def bench(label: str, p99s: list[float], tests_ok: bool = True) -> BenchmarkResult:
    now = datetime.now(timezone.utc)
    runs = [LoadRun(load=LoadReport(label=f"l{i}", vus=500, think_ms=2000, duration_s=20, requests=10, p50_ms=p,
                                    p95_ms=p, p99_ms=p, max_ms=p, avg_ms=p, throughput_rps=100, error_rate=0.0))
            for i, p in enumerate(p99s)]
    passed = 17 if tests_ok else 11
    return BenchmarkResult(service="checkout-service", label=label, repo="/r", started_at=now, finished_at=now,
                           objective=OBJECTIVE, runs=runs,
                           tests=TestReport(total=17, passed=passed, failed=17 - passed, errors=0, skipped=0,
                                            duration_s=1, failures=[]))


def plan() -> ExperimentPlan:
    return ExperimentPlan(rationale="r", concurrency_levels=[100, 500], measurements=["db_activity"],
                          predictions=[Prediction(observation="o", if_supported="s", if_refuted="r")])


def hypothesis(id_: str, title: str, confidence: float) -> Hypothesis:
    return Hypothesis(id=id_, title=title, explanation="e", confidence=confidence, supporting_evidence=[],
                      contradicting_evidence=[], missing_evidence=[], proposed_experiment=plan())


def candidate(name: str) -> PatchCandidate:
    return PatchCandidate(name=name, strategy=f"{name} strategy", expected_effect="faster")


class ScriptedReasoner:
    def __init__(self, hypothesis_rounds, verdicts, candidate_rounds):
        self.hypothesis_rounds = list(hypothesis_rounds)
        self.verdicts = dict(verdicts)
        self.candidate_rounds = list(candidate_rounds)
        self.seen_notebook_sizes = []

    async def form_hypotheses(self, context, limit):
        self.seen_notebook_sizes.append(len(context.notebook))
        return self.hypothesis_rounds.pop(0) if self.hypothesis_rounds else []

    async def conclude(self, context, entry):
        verdict, confidence = self.verdicts[entry.hypothesis.id]
        return ExperimentConclusion(hypothesis_id=entry.hypothesis.id, verdict=verdict, confidence=confidence,
                                    key_observations=["db active connections avg 1.0"], explanation="x")

    async def generate_candidates(self, context, count):
        return self.candidate_rounds.pop(0)


class FakeLab:
    def __init__(self, baseline_p99=3800.0, candidate_results=None, verify_p99s=None):
        self.baseline_result = bench("baseline", [baseline_p99])
        self.candidate_results = candidate_results or {}
        self.verify_p99s = verify_p99s or [20, 22, 19, 25, 21]
        self.experiments = 0
        self.races = 0

    def analyze(self):
        return RepositoryMap(service="checkout-service", objective=OBJECTIVE, tree=["app/main.py"], dependencies=[],
                             entrypoints=[], tests=[], relevant_files=[])

    async def baseline(self):
        return self.baseline_result

    async def experiment(self, plan):
        self.experiments += 1
        return ExperimentResult(plan=plan, levels=[])

    async def race(self, candidates, baseline):
        self.races += 1
        runs = [CandidateRun(candidate=c, diff=f"diff for {c.name}", changed_files=["app/inventory.py"],
                             result=self.candidate_results[c.name]) for c in candidates]
        evaluation = evaluate(baseline, {r.candidate.name: r.result for r in runs}, OBJECTIVE, Constraints())
        return RaceReport(baseline=baseline, runs=runs, evaluation=evaluation)

    async def verify(self, race):
        winner = race.evaluation.winner
        return build_report(bench(winner, self.verify_p99s), OBJECTIVE, bench("baseline", [3800, 3900, 4000]))


def happy_path_reasoner():
    return ScriptedReasoner(
        hypothesis_rounds=[[hypothesis("H1", "Database write contention", 0.58),
                            hypothesis("H2", "Global application lock contention", 0.35)]],
        verdicts={"H1": ("disproved", 0.9), "H2": ("supported", 0.94)},
        candidate_rounds=[[candidate("per-sku-locks"), candidate("atomic-update"), candidate("no-lock")]],
    )


async def test_full_investigation_disproves_then_supports_then_ships_verified_patch():
    lab = FakeLab(candidate_results={
        "per-sku-locks": bench("per-sku-locks", [190]),
        "atomic-update": bench("atomic-update", [71]),
        "no-lock": bench("no-lock", [44], tests_ok=False),
    })
    investigator = Investigator(happy_path_reasoner(), lab)

    outcome = await investigator.run()

    assert outcome.phase == Phase.AWAITING_APPROVAL
    assert outcome.winner == "atomic-update"
    assert outcome.diff == "diff for atomic-update"
    assert outcome.verification.slo_recovered
    assert outcome.context.root_cause.hypothesis.id == "H2"
    assert [e.conclusion.verdict for e in outcome.context.notebook] == ["disproved", "supported"]
    race = outcome.context.races[0].evaluation
    assert race.fastest_rejected == "no-lock"
    messages = [e.message for e in investigator.events]
    assert "H1 DISPROVED (confidence 90%)" in messages
    assert "Root cause: Global application lock contention" in messages
    assert messages[-1] == "Verified patch ready: awaiting human approval"


async def test_stops_when_slo_already_met():
    lab = FakeLab(baseline_p99=40.0)

    outcome = await Investigator(happy_path_reasoner(), lab).run()

    assert outcome.phase == Phase.SLO_ALREADY_MET
    assert lab.experiments == 0


async def test_revises_hypotheses_after_all_are_disproved():
    reasoner = ScriptedReasoner(
        hypothesis_rounds=[[hypothesis("H1", "Database saturation", 0.6)],
                           [hypothesis("H2", "Lock contention", 0.7)]],
        verdicts={"H1": ("disproved", 0.9), "H2": ("supported", 0.9)},
        candidate_rounds=[[candidate("a")]],
    )
    lab = FakeLab(candidate_results={"a": bench("a", [50])})

    outcome = await Investigator(reasoner, lab).run()

    assert outcome.phase == Phase.AWAITING_APPROVAL
    assert reasoner.seen_notebook_sizes == [0, 1]   # the revision saw the disproved hypothesis


async def test_unresolved_when_experiment_budget_runs_out():
    reasoner = ScriptedReasoner(
        hypothesis_rounds=[[hypothesis(f"H{i}", f"Idea {i}", 0.5) for i in range(1, 4)]] * 3,
        verdicts={f"H{i}": ("inconclusive", 0.4) for i in range(1, 4)},
        candidate_rounds=[],
    )
    lab = FakeLab()

    outcome = await Investigator(reasoner, lab, Budget(max_hypotheses=6, max_experiments=2)).run()

    assert outcome.phase == Phase.UNRESOLVED
    assert lab.experiments == 2
    assert "without a supported root cause" in outcome.reason


async def test_weakly_supported_hypothesis_is_not_a_root_cause():
    reasoner = ScriptedReasoner(
        hypothesis_rounds=[[hypothesis("H1", "Maybe the lock", 0.5)]],
        verdicts={"H1": ("supported", 0.6)},
        candidate_rounds=[],
    )

    outcome = await Investigator(reasoner, FakeLab(), Budget(max_hypotheses=1)).run()

    assert outcome.phase == Phase.UNRESOLVED


async def test_retries_candidates_when_every_one_is_rejected():
    reasoner = ScriptedReasoner(
        hypothesis_rounds=[[hypothesis("H1", "Lock contention", 0.8)]],
        verdicts={"H1": ("supported", 0.95)},
        candidate_rounds=[[candidate("racy-1"), candidate("racy-2")], [candidate("fixed")]],
    )
    lab = FakeLab(candidate_results={
        "racy-1": bench("racy-1", [30], tests_ok=False),
        "racy-2": bench("racy-2", [35], tests_ok=False),
        "fixed": bench("fixed", [60]),
    })

    outcome = await Investigator(reasoner, lab).run()

    assert outcome.phase == Phase.AWAITING_APPROVAL
    assert outcome.winner == "fixed"
    assert lab.races == 2


async def test_unresolved_when_verification_does_not_hold():
    reasoner = ScriptedReasoner(
        hypothesis_rounds=[[hypothesis("H1", "Lock contention", 0.8)]],
        verdicts={"H1": ("supported", 0.95)},
        candidate_rounds=[[candidate("lucky")]],
    )
    lab = FakeLab(candidate_results={"lucky": bench("lucky", [90])}, verify_p99s=[90, 150, 180, 95, 160])

    outcome = await Investigator(reasoner, lab, Budget(max_patch_rounds=1)).run()

    assert outcome.phase == Phase.UNRESOLVED
    assert "no candidate recovered the SLO" in outcome.reason
