import { describe, expect, it } from "vitest";

import type { RunEvent } from "../data/types";
import { buildStory, groupStory, stageOf } from "./story";

const T0 = Date.parse("2026-10-24T10:00:00Z");
const ev = (s: number, phase: string, kind: string, message: string, data: Record<string, any> = {}): RunEvent =>
  ({ at: new Date(T0 + s * 1000).toISOString(), phase, kind, message, data });

const plan = { rationale: "r", concurrency_levels: [100, 500], measurements: ["app_spans"], predictions: [] };
const hyp = (id: string, title: string, confidence: number) =>
  ({ id, title, explanation: "e", confidence, supporting_evidence: [], contradicting_evidence: [], missing_evidence: [], proposed_experiment: plan });
const conclusion = (id: string, verdict: string, obs: string) =>
  ({ hypothesis_id: id, verdict, confidence: 0.9, key_observations: [obs], explanation: "Because." });

const RUNNING: RunEvent[] = [
  ev(0, "analyze_repository", "phase", "Analyzing repository"),
  ev(1, "baseline", "phase", "Measuring baseline"),
  ev(5, "baseline", "progress", "[baseline] load 1/3: 500 concurrent, think 2000ms, 20s after 5s warmup"),
  ev(60, "baseline", "baseline", "POST /inventory/reserve p99_ms 763ms (target < 100ms)", { summary: { p99_ms: 763, concurrency: 500 } }),
  ev(61, "form_hypothesis", "phase", "Forming hypotheses"),
  ev(61, "form_hypothesis", "model_call", "start", { task: "form_hypotheses", state: "start" }),
  ev(73, "form_hypothesis", "model_call", "end", { task: "form_hypotheses", state: "end", latency_s: 11.8, prompt_tokens: 5000, completion_tokens: 3461 }),
  ev(73, "form_hypothesis", "hypothesis", "lock", { hypothesis: hyp("lock", "Global asyncio.Lock serializes all reservations, across SKUs", 0.92) }),
  ev(73, "form_hypothesis", "hypothesis", "pool", { hypothesis: hyp("pool", "Connection pool too small", 0.55) }),
  ev(74, "run_experiment", "phase", "Testing lock: Global asyncio.Lock", { plan }),
  ev(80, "run_experiment", "progress", "[experiment] load 1/2: 100 concurrent, think 2000ms"),
];

const FINISHED: RunEvent[] = [
  ...RUNNING,
  ev(140, "run_experiment", "experiment", "done", { hypothesis_id: "lock", result: { plan, levels: [], error: null } }),
  ev(140, "evaluate_evidence", "model_call", "start", { task: "conclude", state: "start" }),
  ev(144, "evaluate_evidence", "model_call", "end", { task: "conclude", state: "end", latency_s: 3.5, prompt_tokens: 2000, completion_tokens: 588 }),
  ev(144, "evaluate_evidence", "conclusion", "SUPPORTED", { hypothesis_id: "lock", conclusion: conclusion("lock", "supported", "Lock wait was 766 ms of a 771 ms p99. Held for only 7 ms.") }),
  ev(144, "root_cause_supported", "root_cause", "Root cause", { hypothesis_id: "lock" }),
  ev(145, "generate_candidates", "phase", "Generating candidate fixes (round 1)"),
  ev(157, "generate_candidates", "candidate", "a", { candidate: { name: "select-for-update", strategy: "Lock the row in Postgres. Then update." } }),
  ev(157, "generate_candidates", "candidate", "b", { candidate: { name: "optimistic-retry", strategy: "Retry on version conflict." } }),
  ev(158, "evaluate_candidates", "phase", "Racing 2 candidates"),
  ev(160, "evaluate_candidates", "progress", "[select-for-update] running tests"),
  ev(300, "evaluate_candidates", "progress", "[optimistic-retry] running tests"),
  ev(500, "evaluate_candidates", "race", "Winner", { evaluation: { winner: "select-for-update", fastest_rejected: "optimistic-retry", candidates: [
    { name: "select-for-update", status: "winner", p99_ms: 8.4, tests_passed: 17, tests_total: 17, reasons: [], failing_tests: [] },
    { name: "optimistic-retry", status: "rejected", p99_ms: 6.1, tests_passed: 16, tests_total: 17, reasons: ["tests failed"], failing_tests: ["tests.test_inventory_concurrency::test_concurrent_reservations_never_oversell[0]"] },
  ] } }),
  ev(501, "verify_winner", "phase", "Verifying select-for-update"),
  ev(900, "verify_winner", "verification", "SLO recovered", { report: { slo_recovered: true, objective: { endpoint: "POST /inventory/reserve", metric: "p99_ms", target: 100 },
    baseline: null, candidate: { runs: 7, tests_passed: 17, tests_total: 17, metric: { n: 7, values: [9, 9, 9, 9, 9, 9, 9], median: 9.1, mean: 9, stdev: 0, ci_low: 8.9, ci_high: 9.3, confidence: 0.95 } } } }),
  ev(900, "awaiting_approval", "phase", "Verified patch ready", { winner: "select-for-update" }),
];

const meta = { endpoint: "POST /inventory/reserve", service: "checkout-service", target: 100, candidates: [] };

describe("buildStory while running", () => {
  it("tells what has happened so far, with the current step still open", () => {
    const story = buildStory(RUNNING, 90_000, meta);
    expect(story.entries.map((e) => e.kind)).toEqual(["measure", "model", "hypotheses", "experiment"]);
    const experiment = story.entries.at(-1)!;
    expect(experiment.kind === "experiment" && [experiment.end, experiment.detail, experiment.hypothesis])
      .toEqual([null, "load 1/2: 100 concurrent", "Global asyncio.Lock serializes all reservations"]);
    expect(story.current?.kind).toBe("experiment");
  });

  it("shows a model call as thinking until it answers", () => {
    const story = buildStory(RUNNING, 65_000, meta);
    const model = story.entries.at(-1)!;
    expect(model.kind === "model" && [model.task, model.end]).toEqual(["form_hypotheses", null]);
    expect(story.tokens).toBe(0);
  });

  it("puts the baseline and the target on the ruler", () => {
    const story = buildStory(RUNNING, 90_000, meta);
    expect(story.markers.map((m) => [m.kind, m.value])).toEqual([["before", 763]]);
    expect(story.target).toBe(100);
  });
});

describe("buildStory when finished", () => {
  const story = buildStory(FINISHED, 1_000_000, meta);

  it("ends verified, with every step in order", () => {
    expect(story.entries.map((e) => e.kind)).toEqual([
      "measure", "model", "hypotheses", "experiment", "model", "verdict", "fixes", "fix", "fix", "verify", "done",
    ]);
    expect(story.after).toBe(9.1);
    expect(story.tokens).toBe(8461 + 2588);
    expect(story.current).toBeNull();
  });

  it("marks the root cause and gives its first sentence of evidence", () => {
    const verdict = story.entries.find((e) => e.kind === "verdict")!;
    expect(verdict.kind === "verdict" && [verdict.verdict, verdict.rootCause, verdict.evidence])
      .toEqual(["supported", true, "Lock wait was 766 ms of a 771 ms p99."]);
  });

  it("gives each fix its result and the reason a rejected one lost", () => {
    const fixes = story.entries.filter((e) => e.kind === "fix");
    expect(fixes.map((f) => f.kind === "fix" && [f.name, f.status, f.p99, f.reason])).toEqual([
      ["select-for-update", "winner", 8.4, null],
      ["optimistic-retry", "rejected", 6.1, "it oversold inventory under concurrent checkout"],
    ]);
    expect(story.safetyRejection).toEqual({
      name: "optimistic-retry",
      p99: 6.1,
      reason: "it oversold inventory under concurrent checkout",
      winner: "select-for-update",
      winnerP99: 8.4,
    });
  });

  it("drops every measured fix and the verified result onto the ruler", () => {
    expect(story.markers.map((m) => [m.kind, m.label, m.value])).toEqual([
      ["before", "before", 763],
      ["winner", "select-for-update", 8.4],
      ["rejected", "optimistic-retry", 6.1],
      ["after", "verified", 9.1],
    ]);
  });
});

describe("stageOf", () => {
  it("follows the story through the five stages", () => {
    expect(stageOf(buildStory(RUNNING, 30_000, meta))).toBe(0);
    expect(stageOf(buildStory(RUNNING, 65_000, meta))).toBe(1);
    expect(stageOf(buildStory(RUNNING, 90_000, meta))).toBe(2);
    expect(stageOf(buildStory(FINISHED, 400_000, meta))).toBe(3);
    expect(stageOf(buildStory(FINISHED, 1_000_000, meta))).toBe(4);
  });
});

describe("groupStory", () => {
  it("folds a finished run into five done steps with one-line results", () => {
    const groups = groupStory(buildStory(FINISHED, 1_000_000, meta), 1_000_000);
    expect(groups.map((g) => [g.name, g.status, g.summary])).toEqual([
      ["Measure", "done", "p99 763 ms with 500 users"],
      ["Form hypotheses", "done", "2 possible causes"],
      ["Run experiments", "done", "1 confirmed"],
      ["Compare fixes", "done", "2 fixes, 1 rejected, select-for-update won"],
      ["Verify the result", "done", "7 runs, median 9.1 ms"],
    ]);
    expect(groups[0].start).toBe(1000);
    expect(groups[0].end).toBe(60_000);
  });

  it("shows the running step and leaves later steps waiting", () => {
    const groups = groupStory(buildStory(RUNNING, 90_000, meta), 90_000);
    expect(groups.map((g) => g.status)).toEqual(["done", "done", "running", "waiting", "waiting"]);
    expect(groups[2].summary).toBe("Testing: Global asyncio.Lock serializes all reservations");
    expect(groups[2].end).toBe(90_000);
  });
});
