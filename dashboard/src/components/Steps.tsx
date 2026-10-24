import { useState } from "react";

import type { Entry, Group, Story } from "../live/story";
import { EntryBody, expandable, toggleLabel } from "./EntryBody";

export function StatusIcon({ status }: { status: Group["status"] }) {
  if (status === "running") return <span className="icon spin" aria-label="Running" />;
  if (status === "waiting") return <span className="icon idle" aria-label="Not started" />;
  return (
    <svg className={`icon ${status}`} viewBox="0 0 16 16" aria-label={status === "done" ? "Done" : "Failed"}>
      <circle cx="8" cy="8" r="7.25" />
      {status === "done" ? <path d="M5 8.2 7.1 10.3 11 6.1" /> : <path d="M5.5 5.5l5 5m0-5-5 5" />}
    </svg>
  );
}

function Row({ entry, story, now, endpoint }: { entry: Entry; story: Story; now: number; endpoint: string }) {
  const [open, setOpen] = useState(false);
  return (
    <li className={`row ${story.current === entry ? "current" : ""}`}>
      <div className="row-body">
        <EntryBody entry={entry} story={story} now={now} endpoint={endpoint} open={open} />
        {expandable(entry) && <button className="link" onClick={() => setOpen(!open)} aria-expanded={open}>{toggleLabel(entry, open)}</button>}
      </div>
    </li>
  );
}

/** The run as five steps, styled like build steps: status, name, one-line result, duration. */
export function Steps({ groups, story, now, endpoint }: { groups: Group[]; story: Story; now: number; endpoint: string }) {
  const [overrides, setOverrides] = useState<Record<number, boolean>>({});
  const finished = story.entries.some((e) => e.kind === "done");
  const done = story.entries.find((e) => e.kind === "done");
  // The closing line goes under the last step, or under the step that failed.
  const doneAt = done?.kind === "done" && !done.verified ? groups.findIndex((g) => g.status === "failed") : groups.length - 1;
  return (
    <ol className="steps">
      {groups.map((g, i) => {
        const auto = g.status === "running" || g.status === "failed" || (finished && i === doneAt);
        const open = (overrides[i] ?? auto) && g.entries.length > 0;
        return (
          <li key={g.name} className={`step s-${g.status}`}>
            <button className="step-head" disabled={!g.entries.length} aria-expanded={open}
                    onClick={() => setOverrides({ ...overrides, [i]: !open })}>
              <StatusIcon status={g.status} />
              <span className="step-name">{g.name}</span>
              <span className="step-summary">{g.summary}</span>
              <svg className="chevron" viewBox="0 0 16 16" aria-hidden><path d="M6 4l4 4-4 4" /></svg>
            </button>
            {open && (
              <ol className="rows">
                {g.entries.filter((e) => e.kind !== "model" || e.end === null || e.failed).map((e) => <Row key={e.id} entry={e} story={story} now={now} endpoint={endpoint} />)}
                {i === doneAt && done && !done.verified && <Row entry={done} story={story} now={now} endpoint={endpoint} />}
              </ol>
            )}
          </li>
        );
      })}
    </ol>
  );
}
