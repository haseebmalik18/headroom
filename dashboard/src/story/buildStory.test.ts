import { describe, expect, it } from "vitest";

import type { Run } from "../data/types";
import { buildStory } from "./buildStory";
import featured from "./fixtures/featured.json";
import unresolved from "./fixtures/unresolved.json";

const kinds = (run: Run) => buildStory(run).map((s) => s.kind);

describe("buildStory", () => {
  it("tells a solved investigation from alert to approval", () => {
    expect(kinds(featured as Run)).toEqual([
      "alert", "hypotheses",
      "experiment", "verdict", "experiment", "verdict", "experiment", "verdict",
      "hypotheses", "experiment", "verdict",
      "fixes", "race", "verify", "approval",
    ]);
  });

  it("pairs each experiment and verdict with its hypothesis and marks the root cause", () => {
    const steps = buildStory(featured as Run);
    const verdicts = steps.filter((s) => s.kind === "verdict");
    expect(verdicts.map((v) => v.kind === "verdict" && [v.conclusion.verdict, v.rootCause])).toEqual([
      ["inconclusive", false], ["disproved", false], ["disproved", false], ["supported", true],
    ]);
    const lastExperiment = steps.filter((s) => s.kind === "experiment").at(-1)!;
    expect(lastExperiment.kind === "experiment" && lastExperiment.hypothesis.id).toBe("sync_pbkdf2_blocks_event_loop");
    const second = steps.filter((s) => s.kind === "hypotheses")[1];
    expect(second.kind === "hypotheses" && second.revision).toBe(true);
  });

  it("carries candidates, the race and the verification", () => {
    const steps = buildStory(featured as Run);
    const fixes = steps.find((s) => s.kind === "fixes")!;
    expect(fixes.kind === "fixes" && fixes.candidates.map((c) => c.status)).toEqual(["winner", "rejected", "valid"]);
    const verify = steps.find((s) => s.kind === "verify")!;
    expect(verify.kind === "verify" && verify.report.slo_recovered).toBe(true);
    const approval = steps.at(-1)!;
    expect(approval.kind === "approval" && approval.winner).toBe("thread_pool_offload");
  });

  it("ends an unresolved investigation with its reason", () => {
    const steps = buildStory(unresolved as Run);
    expect(steps.map((s) => s.kind).slice(-3)).toEqual(["experiment", "verdict", "unresolved"]);
    const last = steps.at(-1)!;
    expect(last.kind === "unresolved" && last.reason).toBe("investigation budget exhausted without a supported root cause");
  });

  it("gives every step a unique key and the index of the event that completes it", () => {
    const steps = buildStory(featured as Run);
    expect(new Set(steps.map((s) => s.key)).size).toBe(steps.length);
    const indexes = steps.map((s) => s.eventIndex);
    expect(indexes).toEqual([...indexes].sort((a, b) => a - b));
    expect(steps.at(-1)!.eventIndex).toBe(featured.events.length - 1);
  });

  it("ignores event kinds it does not know", () => {
    const run = featured as Run;
    const noisy = { ...run, events: [...run.events.slice(0, 5), { ...run.events[4], kind: "mystery" }, ...run.events.slice(5)] };
    expect(kinds(noisy)).toEqual(kinds(run));
  });
});
