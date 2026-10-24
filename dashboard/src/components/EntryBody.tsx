import { formatMs } from "../charts/scale";
import { VerifyDots } from "../charts/VerifyDots";
import type { Entry, Story } from "../live/story";
import { DiffView } from "./DiffView";

const THINKING: Record<string, string> = {
  form_hypotheses: "Nemotron is thinking about what could cause this",
  conclude: "Nemotron is comparing the measurements with its predictions",
  generate_candidates: "Nemotron is writing fixes",
};

export const clock = (ms: number) => {
  const s = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
};

const seconds = (ms: number) => `${Math.max(0, Math.floor(ms / 1000))}s`;
const listUsers = (users: number[]) => users.length > 1
  ? `${users.slice(0, -1).join(", ")} and ${users.at(-1)} users`
  : `${users[0] ?? "?"} users`;

function Running({ entry, now, children }: { entry: Entry; now: number; children: React.ReactNode }) {
  return (
    <>
      <p className="line running">{children}<span className="elapsed">{seconds(now - entry.t)}</span></p>
    </>
  );
}

export function EntryBody({ entry, story, now, endpoint, open }: { entry: Entry; story: Story; now: number; endpoint: string; open: boolean }) {
  const target = formatMs(story.target);
  switch (entry.kind) {
    case "measure":
      return entry.end === null
        ? <Running entry={entry} now={now}>Load-testing <code>{endpoint}</code> to see how slow it is<small>{entry.detail}</small></Running>
        : <p className="line big">With {entry.users} users at once, <code>{endpoint}</code> takes <b className="slow">{formatMs(entry.p99 ?? 0)}</b> at the 99th percentile. It should be under {target}.</p>;

    case "model":
      if (entry.end === null) return <Running entry={entry} now={now}><span className="thinking">{THINKING[entry.task] ?? "Nemotron is working"}</span></Running>;
      return <p className="line quiet">{entry.failed ? "Nemotron's answer did not match the required format." : `Nemotron answered in ${entry.seconds?.toFixed(1)} s, using ${entry.tokens?.toLocaleString("en-US")} tokens.`}</p>;

    case "hypotheses":
      return (
        <>
          <p className="line">{entry.revised ? "With those ruled out, it suggested:" : `It suggested ${entry.items.length} possible causes:`}</p>
          <ol className="causes">
            {entry.items.map((h) => <li key={h.id}>{h.title}<span className="prior">{Math.round(h.prior * 100)}% likely</span></li>)}
          </ol>
        </>
      );

    case "experiment":
      if (entry.end === null) {
        return <Running entry={entry} now={now}>Testing “{entry.hypothesis}” with load tests at {listUsers(entry.users)}<small>{entry.detail}</small></Running>;
      }
      return <p className="line quiet">{entry.error ? `The experiment hit a problem: ${entry.error}` : `Measured it at ${listUsers(entry.users)}.`}</p>;

    case "verdict": {
      const word = entry.verdict === "supported" ? "Confirmed" : entry.verdict === "disproved" ? "Ruled out" : "Unclear";
      return (
        <>
          <p className={`line verdict v-${entry.verdict}`}><b>{word}:</b> {entry.hypothesis}.{entry.rootCause && " This is the root cause."}</p>
          <p className="evidence">{entry.evidence}</p>
          {open && <p className="more">{entry.explanation}</p>}
        </>
      );
    }

    case "fixes":
      return <p className="line">Nemotron wrote {entry.count} different fixes. Each one runs the full test suite and the same load test.</p>;

    case "fix":
      if (entry.status === "waiting") return <p className="line quiet"><code>{entry.name}</code> is waiting its turn.</p>;
      if (entry.status === "running") return <Running entry={entry} now={now}>Testing <code>{entry.name}</code><small>{entry.detail}</small></Running>;
      return (
        <>
          <p className={`line verdict v-${entry.status === "rejected" ? "disproved" : entry.status === "winner" ? "supported" : "valid"}`}>
            {entry.status === "rejected" && <><b>Rejected:</b> <code>{entry.name}</code> because {entry.reason}{entry.p99 !== null && <>. Its {formatMs(entry.p99)} result does not count</>}.</>}
            {entry.status === "winner" && <><b>Fastest valid fix:</b> <code>{entry.name}</code> passed {entry.tests} tests at {formatMs(entry.p99 ?? 0)}.</>}
            {entry.status === "valid" && <><code>{entry.name}</code> passed {entry.tests} tests at {formatMs(entry.p99 ?? 0)}.</>}
          </p>
          {open && <><p className="more">{entry.strategy}</p>{entry.diff && <DiffView diff={entry.diff} />}</>}
        </>
      );

    case "verify":
      if (entry.end === null || !entry.report) {
        return <Running entry={entry} now={now}>Re-running <code>{entry.winner}</code> several more times to make sure it holds<small>{entry.detail}</small></Running>;
      }
      return (
        <>
          <p className={`line big verdict v-${entry.report.slo_recovered ? "supported" : "disproved"}`}>
            {entry.report.slo_recovered
              ? <>{entry.report.candidate.runs} runs: median <b className="fast">{formatMs(entry.report.candidate.metric.median)}</b>. Correctness tests passed.</>
              : <>It did not hold across {entry.report.candidate.runs} runs, so the fix was not accepted.</>}
          </p>
          <details className="measurement-details">
            <summary>Repeated-run measurements</summary>
            {entry.report.slo_recovered && <p className="more">The 95% confidence interval is below the {target} target.</p>}
            <VerifyDots baseline={entry.report.baseline?.metric ?? null} patched={entry.report.candidate.metric} target={story.target} />
          </details>
        </>
      );

    case "done":
      return entry.verified
        ? (
          <>
            <p className="line big">Done. <code>{entry.winner}</code> is ready for a person to review and approve.</p>
            {open && entry.diff && <DiffView diff={entry.diff} />}
          </>
        )
        : <p className="line big">Stopped without a fix: {entry.reason}</p>;
  }
}

export const expandable = (e: Entry) =>
  e.kind === "verdict" || (e.kind === "fix" && (e.status === "winner" || e.status === "valid" || e.status === "rejected")) ||
  (e.kind === "done" && e.verified && e.diff !== null);

export const toggleLabel = (e: Entry, open: boolean) => {
  if (e.kind === "verdict") return open ? "Hide reasoning" : "Show reasoning";
  return open ? "Hide code" : "Show code";
};
