"""Export a recorded investigation as a compact replay for the dashboard.

Each investigation becomes one JSON file: the event log as recorded, every raced
candidate with its diff and verdict, the outcome with its verification runs, and
model usage. Repository contents and raw benchmark payloads are left out. An
index of every exported run is rebuilt alongside.
"""

import json
from pathlib import Path

from headroom.agent.store import InvestigationStore
from headroom.evals import load_scenarios


def _scenario_for(repo: Path) -> str | None:
    try:
        scenarios = load_scenarios()
    except FileNotFoundError:
        return None
    # A scenario with its own objective runs from a prepared copy named after it (see evals.prepare).
    by_copy = next((s.name for s in scenarios if s.objective and Path(repo).name == s.name), None)
    return by_copy or next((s.name for s in scenarios if not s.objective and str(repo).endswith(str(s.repo))), None)


def _candidates(context) -> list[dict]:
    rows = []
    for round_, report in enumerate(context.races if context else [], start=1):
        runs = {r.candidate.name: r for r in report.runs}
        for c in report.evaluation.candidates:
            run = runs[c.name]
            rows.append({
                "round": round_,
                "name": c.name,
                "strategy": run.candidate.strategy,
                "expected_effect": run.candidate.expected_effect,
                "risks": run.candidate.risks,
                "changed_files": run.changed_files,
                "diff": run.diff,
                "status": c.status,
                "reasons": c.reasons,
                "failing_tests": c.failing_tests,
                "p99_ms": c.p99_ms,
                "throughput_rps": c.throughput_rps,
                "tests_passed": c.tests_passed,
                "tests_total": c.tests_total,
                "meets_slo": c.meets_slo,
            })
    return rows


def _usage(store_path: Path) -> tuple[str | None, dict]:
    path = store_path / "model_calls.json"
    calls = json.loads(path.read_text()) if path.exists() else []
    model = calls[0]["model"] if calls else None
    rows = [{k: c[k] for k in ("task", "latency_s", "prompt_tokens", "completion_tokens")} for c in calls]
    total = sum(c["prompt_tokens"] + c["completion_tokens"] for c in calls)
    return model, {"calls": rows, "total_tokens": total}


def build_run(store: InvestigationStore, actions_url: str | None = None) -> dict:
    outcome = store.outcome()
    events = store.events()
    context = outcome.context
    objective = context.baseline.objective if context else None
    model, usage = _usage(store.path)

    final_ms = None
    if outcome.verification:
        final_ms = outcome.verification.candidate.metric.median
    elif context and context.races and context.races[-1].evaluation.winner:
        evaluation = context.races[-1].evaluation
        final_ms = next(c.metric_value for c in evaluation.candidates if c.name == evaluation.winner)

    return {
        "id": store.path.name,
        "recorded_at": events[0].at.isoformat() if events else None,
        "service": store.repo.name,
        "scenario": _scenario_for(store.repo),
        "model": model,
        "actions_url": actions_url,
        "objective": objective.model_dump(mode="json") if objective else None,
        "baseline_ms": context.baseline.median_load(objective.metric) if context else None,
        "final_ms": final_ms,
        "events": [e.model_dump(mode="json") for e in events],
        "candidates": _candidates(context),
        "outcome": {
            "phase": outcome.phase.value,
            "winner": outcome.winner,
            "diff": outcome.diff,
            "reason": outcome.reason,
            "verification": outcome.verification.model_dump(mode="json") if outcome.verification else None,
        },
        "usage": usage,
    }


def _summary(run: dict) -> dict:
    objective = run["objective"] or {}
    return {
        "id": run["id"],
        "title": run["scenario"] or run["service"],
        "scenario": run["scenario"],
        "service": run["service"],
        "endpoint": objective.get("endpoint"),
        "phase": run["outcome"]["phase"],
        "winner": run["outcome"]["winner"],
        "baseline_ms": run["baseline_ms"],
        "final_ms": run["final_ms"],
        "recorded_at": run["recorded_at"],
        "actions_url": run["actions_url"],
    }


def write_index(out_dir: Path, featured: str | None = None) -> Path:
    index_path = out_dir / "index.json"
    if featured is None and index_path.exists():
        featured = json.loads(index_path.read_text()).get("featured")
    runs = [json.loads(p.read_text()) for p in sorted(out_dir.glob("*.json")) if p.name != "index.json"]
    summaries = sorted((_summary(r) for r in runs), key=lambda s: s["recorded_at"] or "", reverse=True)
    index_path.write_text(json.dumps({"featured": featured, "runs": summaries}, indent=2))
    return index_path


def export_investigation(path: Path, out_dir: Path, *, actions_url: str | None = None,
                         featured: bool = False) -> Path:
    store = InvestigationStore.open(str(path))
    run = build_run(store, actions_url)
    out_dir.mkdir(parents=True, exist_ok=True)
    run_path = out_dir / f"{run['id']}.json"
    run_path.write_text(json.dumps(run, separators=(",", ":")))
    write_index(out_dir, featured=run["id"] if featured else None)
    return run_path
