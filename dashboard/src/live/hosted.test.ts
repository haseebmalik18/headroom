import { describe, expect, it } from "vitest";
import { isLegacyCompletedRun, normalizeFailureMode, receive, type LiveRun } from "./hosted";

const run: LiveRun = { id: "one", seed: 42, state: "running", created_at: 0, message: "Running", execution_url: null, diff: null, challenge: null };
const event = { at: "2026-10-24T12:00:00Z", phase: "baseline", kind: "phase", message: "Measuring baseline", data: {} };
describe("live event recovery", () => {
  it("accepts current and persisted failure names", () => {
    expect(normalizeFailureMode("checkout")).toBe("checkout");
    expect(normalizeFailureMode("lock-contention")).toBe("checkout");
    expect(normalizeFailureMode("n-plus-one")).toBe("catalog");
    expect(normalizeFailureMode("Catalog under load")).toBe("catalog");
    expect(normalizeFailureMode("blocking-event-loop")).toBe("auth");
    expect(normalizeFailureMode("Authentication under load")).toBe("auth");
    expect(normalizeFailureMode("sequential-queries")).toBe("dashboard");
    expect(normalizeFailureMode("pricing")).toBe("pricing");
    expect(normalizeFailureMode("cache-stampede")).toBe("pricing");
    expect(normalizeFailureMode("Pricing during a sale")).toBe("pricing");
    expect(normalizeFailureMode(undefined)).toBe("checkout");
    expect(normalizeFailureMode("unexpected-value")).toBe("checkout");
  });
  it("hides only completed runs from the previous schema", () => {
    const legacy = { ...run, state: "done" as const, challenge: { title: "Catalog under load", dataset: "legacy", concurrency: 60,
      fingerprint: "old", objective: { endpoint: "GET /catalog", target: 50 } } };
    expect(isLegacyCompletedRun(legacy)).toBe(true);
    expect(isLegacyCompletedRun({ ...legacy, failure: "catalog" })).toBe(false);
    expect(isLegacyCompletedRun({ ...legacy, state: "running" })).toBe(false);
  });
  it("resumes a complete snapshot and ignores duplicate delivery", () => {
    const initial = receive({ run: null, events: [] }, { type: "snapshot", run, events: [event] });
    expect(receive(initial, { type: "event", run, event, sequence: 0 })).toEqual(initial);
    expect(receive(initial, { type: "event", run, event, sequence: 1 }).events).toHaveLength(2);
  });
  it("requires a fresh snapshot for gaps or a different run", () => {
    expect(() => receive({ run, events: [] }, { type: "event", run, event, sequence: 2 })).toThrow();
    expect(() => receive({ run, events: [] }, { type: "state", run: { ...run, id: "two" } })).toThrow();
  });
  it("keeps evidence and final patch when the runner finishes", () => {
    const finished = receive({ run, events: [event] }, { type: "state", run: { ...run, state: "done", diff: "patch" } });
    expect(finished.events).toEqual([event]);
    expect(finished.run?.diff).toBe("patch");
  });
});
