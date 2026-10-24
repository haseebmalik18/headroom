import type { Candidate, Hypothesis, RunEvent, Verification } from "../data/types";
import { metricName, show } from "./goal";
import { explainTestFailure, firstSentence, shortTitle } from "./text";

/** One thing that happened, told as a sentence on the page. `end` is null while it is still happening. */
export type Entry =
  | { kind: "measure"; id: string; t: number; end: number | null; users: number | null; value: number | null; detail: string }
  | { kind: "model"; id: string; t: number; end: number | null; task: string; seconds: number | null; tokens: number | null; failed: boolean }
  | { kind: "hypotheses"; id: string; t: number; revised: boolean; items: { id: string; title: string; prior: number }[] }
  | { kind: "experiment"; id: string; t: number; end: number | null; hypothesis: string; users: number[]; detail: string; error: string | null }
  | { kind: "verdict"; id: string; t: number; verdict: string; hypothesis: string; evidence: string; explanation: string; rootCause: boolean }
  | { kind: "fixes"; id: string; t: number; round: number; count: number }
  | { kind: "fix"; id: string; t: number; end: number | null; name: string; strategy: string; started: boolean;
      status: "waiting" | "running" | "winner" | "valid" | "rejected"; value: number | null; tests: string | null;
      reason: string | null; detail: string; diff: string | null }
  | { kind: "verify"; id: string; t: number; end: number | null; winner: string | null; report: Verification | null; detail: string }
  | { kind: "done"; id: string; t: number; verified: boolean; winner: string | null; reason: string | null; diff: string | null };

export interface Marker {
  kind: "before" | "winner" | "valid" | "rejected" | "after";
  label: string;
  value: number;
}

export interface Story {
  entries: Entry[];
  current: Entry | null; // the step happening right now
  markers: Marker[];
  metric: string; // the goal: what is measured, and its target
  target: number;
  before: number | null;
  after: number | null;
  tokens: number;
  calls: number;
  safetyRejection: {
    name: string;
    value: number;
    reason: string;
    winner: string | null;
    winnerValue: number | null;
  } | null;
}

export interface Meta {
  endpoint: string;
  service: string;
  metric?: string; // defaults to p99_ms; live runs also learn it from the baseline event
  target: number;
  candidates: Candidate[]; // from the export, for diffs; empty when live
}

const SCOPE = /^\[(.+?)\]\s*(.*)$/;

function cleanProgress(message: string): string {
  return message.replace(/, think [\d.]+ms.*$/, "").replace(/\s*\((?:headroom|hotpath)-[^)]*\)/, "");
}

/** Everything that has happened by `now` (ms since the first event), as story entries and ruler markers. */
export function buildStory(events: RunEvent[], now: number, meta: Meta): Story {
  const t0 = events.length ? Date.parse(events[0].at) : 0;
  const story: Story = {
    entries: [], current: null, markers: [], metric: meta.metric ?? "p99_ms", target: meta.target, before: null, after: null,
    tokens: 0, calls: 0, safetyRejection: null,
  };
  const titles = new Map<string, string>();
  const fixes = new Map<string, Extract<Entry, { kind: "fix" }>>();
  let phase = "";
  let round = 0;
  let winner: string | null = null;
  let reason: string | null = null;
  const open = <E extends Entry>(entry: E): E => {
    story.entries.push(entry);
    return entry;
  };
  const last = <K extends Entry["kind"]>(kind: K) =>
    [...story.entries].reverse().find((e) => e.kind === kind) as Extract<Entry, { kind: K }> | undefined;

  for (const event of events) {
    const t = Date.parse(event.at) - t0;
    if (t > now) break;
    const data = event.data ?? {};
    const id = `${event.kind}-${story.entries.length}`;

    switch (event.kind) {
      case "phase":
        phase = event.phase;
        if (phase === "baseline") open({ kind: "measure", id, t, end: null, users: null, value: null, detail: "starting the service" });
        if (phase === "run_experiment") {
          const hid = event.message.match(/^Testing (.+?): /)?.[1] ?? "";
          open({ kind: "experiment", id, t, end: null, hypothesis: titles.get(hid) ?? hid,
                 users: data.plan?.concurrency_levels ?? [], detail: "starting the service", error: null });
        }
        if (phase === "generate_candidates") {
          round += 1;
          fixes.clear();
        }
        if (phase === "verify_winner") open({ kind: "verify", id, t, end: null, winner, report: null, detail: "starting" });
        if (phase === "awaiting_approval" || phase === "unresolved" || phase === "slo_already_met") {
          if (phase === "unresolved") reason = event.message.replace(/^Unresolved: /, "");
          const diff = meta.candidates.find((c) => c.name === winner)?.diff ?? null;
          open({ kind: "done", id, t, verified: phase === "awaiting_approval", winner, reason, diff });
        }
        break;

      case "progress": {
        const [, scope = "", rest = event.message] = event.message.match(SCOPE) ?? [];
        const detail = cleanProgress(rest);
        if (phase === "baseline") last("measure") && (last("measure")!.detail = detail);
        if (phase === "run_experiment") last("experiment") && (last("experiment")!.detail = detail);
        if (phase === "verify_winner") last("verify") && (last("verify")!.detail = `${scope === "verify baseline" ? "original code" : "the fix"}: ${detail}`);
        const fix = fixes.get(scope);
        if (phase === "evaluate_candidates" && fix) {
          if (!fix.started) {
            fix.started = true;
            fix.t = t; // the fix moves to the bottom of the story when it starts running
            story.entries.splice(story.entries.indexOf(fix), 1);
            story.entries.push(fix);
          }
          fix.status = "running";
          fix.detail = detail;
        }
        break;
      }

      case "model_call":
        if (data.state === "start") {
          open({ kind: "model", id, t, end: null, task: data.task, seconds: null, tokens: null, failed: false });
        } else {
          const call = last("model");
          if (!call || call.end !== null) break;
          call.end = t;
          call.failed = data.state === "failed";
          call.seconds = data.latency_s ?? null;
          if (!call.failed) {
            const tokens = (data.prompt_tokens ?? 0) + (data.completion_tokens ?? 0);
            call.tokens = tokens;
            story.tokens += tokens;
            story.calls += 1;
          }
        }
        break;

      case "baseline": {
        const measure = last("measure");
        if (data.objective) Object.assign(story, { metric: data.objective.metric, target: data.objective.target });
        story.before = data.summary?.[story.metric] ?? null;
        if (measure) Object.assign(measure, { end: t, value: story.before, users: data.summary?.concurrency ?? null });
        if (story.before !== null) story.markers.push({ kind: "before", label: "before", value: story.before });
        break;
      }

      case "hypothesis": {
        const h = data.hypothesis as Hypothesis;
        titles.set(h.id, shortTitle(h.title));
        const previous = story.entries.at(-1);
        const item = { id: h.id, title: shortTitle(h.title), prior: h.confidence };
        if (previous?.kind === "hypotheses") previous.items.push(item);
        else open({ kind: "hypotheses", id, t, revised: story.entries.some((e) => e.kind === "hypotheses"), items: [item] });
        break;
      }

      case "experiment": {
        const experiment = last("experiment");
        if (experiment) Object.assign(experiment, { end: t, error: data.result?.error ? firstSentence(data.result.error, 120) : null });
        break;
      }

      case "conclusion": {
        const c = data.conclusion;
        open({ kind: "verdict", id, t, verdict: c.verdict, hypothesis: titles.get(data.hypothesis_id) ?? data.hypothesis_id,
               evidence: firstSentence(c.key_observations[0] ?? ""), explanation: c.explanation, rootCause: false });
        break;
      }

      case "root_cause": {
        const verdict = last("verdict");
        if (verdict) verdict.rootCause = true;
        break;
      }

      case "candidate": {
        const c = data.candidate;
        const group = last("fixes");
        if (group?.round === round) group.count += 1;
        else open({ kind: "fixes", id: `fixes-${round}`, t, round, count: 1 });
        const diff = meta.candidates.find((x) => x.name === c.name && x.round === round)?.diff ?? null;
        fixes.set(c.name, open({ kind: "fix", id, t, end: null, name: c.name, strategy: firstSentence(c.strategy, 160), started: false,
                                 status: "waiting", value: null, tests: null, reason: null, detail: "", diff }));
        break;
      }

      case "race":
        winner = data.evaluation?.winner ?? null;
        for (const c of data.evaluation?.candidates ?? []) {
          const fix = fixes.get(c.name);
          if (!fix) continue;
          const value: number | null = c.metric_value ?? c.p99_ms;
          Object.assign(fix, {
            end: t, status: c.status, value, tests: c.tests_total ? `${c.tests_passed} of ${c.tests_total}` : null,
            reason: c.status === "rejected"
              ? (c.failing_tests[0] ? explainTestFailure(c.failing_tests[0]) : (c.reasons[0] ?? "").split("\n")[0])
              : null,
          });
          if (value !== null) story.markers.push({ kind: c.status, label: c.name, value });
        }
        {
          const rejected = fixes.get(data.evaluation?.fastest_rejected);
          const selected = winner ? fixes.get(winner) : null;
          if (rejected?.status === "rejected" && rejected.value !== null && rejected.reason) {
            story.safetyRejection = {
              name: rejected.name,
              value: rejected.value,
              reason: rejected.reason,
              winner: selected?.name ?? null,
              winnerValue: selected?.value ?? null,
            };
          }
        }
        break;

      case "verification": {
        const report = data.report as Verification;
        const verify = last("verify");
        if (verify) Object.assign(verify, { end: t, report });
        if (report.slo_recovered) {
          story.after = report.candidate.metric.median;
          story.markers.push({ kind: "after", label: "verified", value: story.after });
        }
        break;
      }
    }
  }

  const running = story.entries.filter((e) => "end" in e && e.end === null && !(e.kind === "fix" && !e.started));
  story.current = running.at(-1) ?? null;
  return story;
}

export const STAGES = [
  { name: "Measure", about: "Load-test the slow endpoint to see how bad it is." },
  { name: "Form hypotheses", about: "Nemotron reads the code and proposes possible causes." },
  { name: "Run experiments", about: "An experiment on the running service confirms or rules out each one." },
  { name: "Compare fixes", about: "Nemotron writes several fixes. Any that break a test are thrown out." },
  { name: "Verify the result", about: "Repeated benchmarks check correctness and the confidence interval against the target." },
] as const;

const STAGE_OF: Record<Entry["kind"], number> = {
  measure: 0, hypotheses: 1, experiment: 2, verdict: 2, fixes: 3, fix: 3, verify: 4, done: 4, model: -1,
};

/** Which of the five stages the story has reached, counting a model call as part of the stage it serves. */
export function stageOf(story: Story): number {
  let stage = 0;
  for (const e of story.entries) {
    if (e.kind === "model") stage = Math.max(stage, e.task === "form_hypotheses" ? 1 : e.task === "generate_candidates" ? 3 : 2);
    else stage = Math.max(stage, STAGE_OF[e.kind]);
  }
  return stage;
}

export interface Group {
  name: string;
  status: "waiting" | "running" | "done" | "failed";
  summary: string;
  start: number | null;
  end: number | null;
  entries: Entry[];
}

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function stageOfEntry(e: Entry): number {
  if (e.kind === "model") return e.task === "form_hypotheses" ? 1 : e.task === "generate_candidates" ? 3 : 2;
  return STAGE_OF[e.kind];
}

const isRunning = (e: Entry) => "end" in e && e.end === null && !(e.kind === "fix" && !e.started);

function summarize(stage: number, entries: Entry[], running: Entry | undefined, metric: string): string {
  const fmt = (value: number) => show(metric, value);
  if (running) {
    switch (running.kind) {
      case "measure": return running.detail || "Starting the service";
      case "model": return "Nemotron is thinking";
      case "experiment": return `Testing: ${running.hypothesis}`;
      case "fix": return `Testing ${running.name}`;
      case "verify": return `Re-running ${running.winner ?? "the fix"}`;
    }
  }
  switch (stage) {
    case 0: {
      const m = entries.find((e) => e.kind === "measure");
      return m?.kind === "measure" && m.value !== null ? `${metricName(metric)} ${fmt(m.value)} with ${m.users} users` : "";
    }
    case 1:
      return plural(entries.reduce((n, e) => n + (e.kind === "hypotheses" ? e.items.length : 0), 0), "possible cause");
    case 2: {
      const verdicts = entries.filter((e) => e.kind === "verdict");
      const count = (v: string) => verdicts.filter((e) => e.kind === "verdict" && e.verdict === v).length;
      return [
        count("supported") && `${count("supported")} confirmed`,
        count("disproved") && `${count("disproved")} ruled out`,
        count("inconclusive") && `${count("inconclusive")} unclear`,
      ].filter(Boolean).join(", ");
    }
    case 3: {
      const fixes = entries.filter((e) => e.kind === "fix");
      const rejected = fixes.filter((e) => e.kind === "fix" && e.status === "rejected").length;
      const winner = fixes.find((e) => e.kind === "fix" && e.status === "winner");
      return [plural(fixes.length, "fix").replace("fixs", "fixes"), rejected && `${rejected} rejected`,
              winner?.kind === "fix" && `${winner.name} won`].filter(Boolean).join(", ");
    }
    default: {
      const v = entries.find((e) => e.kind === "verify");
      return v?.kind === "verify" && v.report ? `${v.report.candidate.runs} runs, median ${fmt(v.report.candidate.metric.median)}` : "";
    }
  }
}

/** The run as five steps, like build steps: each with a status, a one-line result and how long it took. */
export function groupStory(story: Story, now: number): Group[] {
  const done = story.entries.find((e) => e.kind === "done");
  const reached = stageOf(story);
  return STAGES.map((s, i) => {
    const entries = story.entries.filter((e) => e.kind !== "done" && stageOfEntry(e) === i);
    const running = entries.filter(isRunning).at(-1);
    let status: Group["status"] = "waiting";
    if (entries.length) status = running || (i === reached && !done) ? "running" : "done";
    if (done?.kind === "done" && !done.verified && entries.length && i === reached) status = "failed";
    if (i === 4 && entries.some((e) => e.kind === "verify" && e.report && !e.report.slo_recovered)) status = "failed";
    const start = entries.length ? Math.min(...entries.map((e) => e.t)) : null;
    const ends = entries.map((e) => ("end" in e ? e.end ?? now : e.t));
    return {
      name: s.name, status, entries, start,
      end: entries.length ? (status === "running" ? now : Math.max(...ends)) : null,
      summary: summarize(i, entries, running, story.metric),
    };
  });
}
