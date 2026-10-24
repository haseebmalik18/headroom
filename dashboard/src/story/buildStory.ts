import type {
  Candidate, Conclusion, ExperimentPlan, ExperimentResult, Hypothesis, Objective, Run, Verification,
} from "../data/types";

interface Base {
  key: string;
  title: string;
  eventIndex: number; // index of the recorded event that completes this step
}

export type Step = Base & (
  | { kind: "alert"; objective: Objective | null; summary: Record<string, any>; message: string }
  | { kind: "hypotheses"; revision: boolean; hypotheses: Hypothesis[] }
  | { kind: "experiment"; hypothesis: Hypothesis; plan: ExperimentPlan; result: ExperimentResult }
  | { kind: "verdict"; hypothesis: Hypothesis; conclusion: Conclusion; rootCause: boolean }
  | { kind: "fixes"; round: number; candidates: Candidate[] }
  | { kind: "race"; round: number; evaluation: Record<string, any>; candidates: Candidate[] }
  | { kind: "verify"; winner: string | null; report: Verification }
  | { kind: "approval"; winner: string | null; diff: string | null }
  | { kind: "unresolved"; reason: string | null }
);

export type StepKind = Step["kind"];

const TERMINAL = new Set(["awaiting_approval", "slo_already_met", "unresolved"]);

/** Turn a recorded run into the ordered steps of its story. Unknown event kinds are skipped. */
export function buildStory(run: Run): Step[] {
  const steps: Step[] = [];
  const hypotheses = new Map<string, Hypothesis>();
  const seen = new Map<string, number>();
  let fixRound = 0;
  let raceRound = 0;
  let winner: string | null = null;

  const key = (base: string) => {
    const n = (seen.get(base) ?? 0) + 1;
    seen.set(base, n);
    return n === 1 ? base : `${base}-${n}`;
  };
  const last = () => steps.at(-1);

  run.events.forEach((event, i) => {
    const data = event.data ?? {};
    switch (event.kind) {
      case "baseline":
        steps.push({ kind: "alert", key: key("alert"), title: "Alert", eventIndex: i,
                     objective: run.objective, summary: data.summary ?? {}, message: event.message });
        break;
      case "hypothesis": {
        const h = data.hypothesis as Hypothesis;
        hypotheses.set(h.id, h);
        const prev = last();
        if (prev?.kind === "hypotheses" && prev.eventIndex === i - 1) {
          prev.hypotheses.push(h);
          prev.eventIndex = i;
        } else {
          const revision = steps.some((s) => s.kind === "hypotheses");
          steps.push({ kind: "hypotheses", key: key("hypotheses"), eventIndex: i, revision, hypotheses: [h],
                       title: revision ? "Revised hypotheses" : "Hypotheses" });
        }
        break;
      }
      case "experiment": {
        const h = hypotheses.get(data.hypothesis_id);
        if (!h) break;
        const result = data.result as ExperimentResult;
        steps.push({ kind: "experiment", key: key(`experiment-${h.id}`), title: `Experiment: ${h.title}`,
                     eventIndex: i, hypothesis: h, plan: result.plan, result });
        break;
      }
      case "conclusion": {
        const h = hypotheses.get(data.hypothesis_id);
        if (!h) break;
        const conclusion = data.conclusion as Conclusion;
        steps.push({ kind: "verdict", key: key(`verdict-${h.id}`), title: `${conclusion.verdict}: ${h.title}`,
                     eventIndex: i, hypothesis: h, conclusion, rootCause: false });
        break;
      }
      case "root_cause": {
        const verdict = [...steps].reverse().find((s) => s.kind === "verdict");
        if (verdict?.kind === "verdict") verdict.rootCause = true;
        break;
      }
      case "candidate": {
        const prev = last();
        if (prev?.kind === "fixes" && prev.round === fixRound) {
          prev.eventIndex = i;
        } else {
          fixRound += 1;
          steps.push({ kind: "fixes", key: key(`fixes-${fixRound}`), title: `Candidate fixes (round ${fixRound})`,
                       eventIndex: i, round: fixRound, candidates: run.candidates.filter((c) => c.round === fixRound) });
        }
        break;
      }
      case "race": {
        raceRound += 1;
        winner = data.evaluation?.winner ?? null;
        steps.push({ kind: "race", key: key(`race-${raceRound}`), title: `Race (round ${raceRound})`, eventIndex: i,
                     round: raceRound, evaluation: data.evaluation ?? {},
                     candidates: run.candidates.filter((c) => c.round === raceRound) });
        break;
      }
      case "verification":
        steps.push({ kind: "verify", key: key("verify"), title: "Verification", eventIndex: i, winner,
                     report: data.report as Verification });
        break;
      case "phase":
        if (!TERMINAL.has(event.phase)) break;
        if (event.phase === "awaiting_approval") {
          steps.push({ kind: "approval", key: key("approval"), title: "Awaiting approval", eventIndex: i,
                       winner: run.outcome.winner, diff: run.outcome.diff });
        } else {
          steps.push({ kind: "unresolved", key: key("unresolved"),
                       title: event.phase === "slo_already_met" ? "SLO already met" : "Unresolved",
                       eventIndex: i, reason: run.outcome.reason });
        }
        break;
    }
  });
  return steps;
}
