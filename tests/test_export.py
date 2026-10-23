import json
from pathlib import Path

from test_investigator import FakeLab, ScriptedReasoner, bench, candidate, hypothesis

from hotpath.agent.investigator import Investigator
from hotpath.agent.store import InvestigationStore
from hotpath.export import export_investigation
from hotpath.models.nemotron import ModelCall

CHECKOUT = Path(__file__).resolve().parents[1] / "examples" / "checkout-service"


async def _record(root: Path, rounds=None) -> Path:
    """Run a scripted investigation and save it exactly as `hotpath investigate` does."""
    reasoner = ScriptedReasoner(
        hypothesis_rounds=[[hypothesis("H1", "Database write contention", 0.6),
                            hypothesis("H2", "Global lock contention", 0.35)]],
        verdicts={"H1": ("disproved", 0.9), "H2": ("supported", 0.94)},
        candidate_rounds=rounds or [[candidate("no-lock"), candidate("atomic-update")]],
    )
    lab = FakeLab(candidate_results={
        "no-lock": bench("no-lock", [9], tests_ok=False),
        "atomic-update": bench("atomic-update", [12]),
        "slow-fix": bench("slow-fix", [3700]),
    })
    store = InvestigationStore.create(CHECKOUT, root=root)
    investigator = Investigator(reasoner, lab, on_event=store.record)
    outcome = await investigator.run()
    calls = [ModelCall(task="form_hypotheses", model="nvidia/nemotron-test", latency_s=2.0,
                       prompt_tokens=100, completion_tokens=50, attempts=1),
             ModelCall(task="conclude", model="nvidia/nemotron-test", latency_s=1.0,
                       prompt_tokens=30, completion_tokens=20, attempts=1)]
    store.save_outcome(outcome, calls)
    return store.path


async def test_exports_a_compact_replay_of_the_investigation(tmp_path):
    recorded = await _record(tmp_path / "investigations")
    out = tmp_path / "runs"

    path = export_investigation(recorded, out, actions_url="https://github.com/o/r/actions/runs/1")

    run = json.loads(path.read_text())
    assert run["id"] == recorded.name
    assert run["service"] == "checkout-service"
    assert run["scenario"] == "lock-contention"
    assert run["model"] == "nvidia/nemotron-test"
    assert run["actions_url"] == "https://github.com/o/r/actions/runs/1"
    assert run["objective"] == {"endpoint": "POST /inventory/reserve", "metric": "p99_ms", "target": 100.0}
    assert len(run["events"]) == len((recorded / "events.jsonl").read_text().splitlines())
    by_name = {c["name"]: c for c in run["candidates"]}
    assert by_name["no-lock"]["status"] == "rejected"
    assert by_name["no-lock"]["reasons"] == ["tests failed: 6 of 17 tests failed"]
    assert by_name["atomic-update"]["status"] == "winner"
    assert by_name["atomic-update"]["diff"] == "diff for atomic-update"
    assert by_name["atomic-update"]["round"] == 1
    assert run["outcome"]["phase"] == "awaiting_approval"
    assert run["outcome"]["winner"] == "atomic-update"
    assert run["outcome"]["verification"]["candidate"]["metric"]["values"] == [20, 22, 19, 25, 21]
    assert run["usage"]["total_tokens"] == 200
    assert run["usage"]["calls"][0] == {"task": "form_hypotheses", "latency_s": 2.0,
                                        "prompt_tokens": 100, "completion_tokens": 50}
    assert "repo_map" not in path.read_text()


async def test_index_lists_runs_and_keeps_the_featured_one(tmp_path):
    first = await _record(tmp_path / "a")
    second = await _record(tmp_path / "b", rounds=[[candidate("slow-fix")], [candidate("atomic-update")]])
    second = second.rename(second.with_name("20991231-235959-checkout-service"))  # ids are per-second timestamps
    out = tmp_path / "runs"

    export_investigation(first, out, featured=True)
    export_investigation(second, out)

    index = json.loads((out / "index.json").read_text())
    assert index["featured"] == first.name
    assert {r["id"] for r in index["runs"]} == {first.name, second.name}
    summary = next(r for r in index["runs"] if r["id"] == first.name)
    assert summary["title"] == "lock-contention"
    assert summary["endpoint"] == "POST /inventory/reserve"
    assert summary["phase"] == "awaiting_approval"
    assert summary["winner"] == "atomic-update"
    assert summary["baseline_ms"] == 3800
    assert summary["final_ms"] == 21
    multi = json.loads((out / f"{second.name}.json").read_text())
    assert [(c["round"], c["name"]) for c in multi["candidates"]] == [(1, "slow-fix"), (2, "atomic-update")]
