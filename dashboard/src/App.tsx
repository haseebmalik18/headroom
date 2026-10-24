import { useEffect, useMemo, useState } from "react";

import { formatMs } from "./charts/scale";
import { DiffView } from "./components/DiffView";
import { clock } from "./components/EntryBody";
import { Steps } from "./components/Steps";
import { loadIndex, loadRun } from "./data/load";
import type { Run, RunEvent, RunIndex } from "./data/types";
import { useLiveFeed } from "./live/sources";
import { isLegacyCompletedRun, normalizeFailureMode, useHostedFeed, type FailureMode } from "./live/hosted";
import { buildStory, groupStory, type Meta } from "./live/story";
import { formatHash, parseHash } from "./replay/hash";

const REPO_URL = "https://github.com/haseebmalik18/hotpath";
const LIVE = "live";
const HOSTED = import.meta.env.MODE === "cloudflare";
const TITLES: Record<string, string> = {
  "lock-contention": "Slow checkout under load",
  "n-plus-one": "Slow catalog pages",
  "blocking-event-loop": "Stalling profile requests",
};

type Tab = "investigation" | "patch";

function Investigation({ title, events, meta, now, controls, footer, finalDiff = null }: {
  title: string; events: RunEvent[]; meta: Meta; now: number; controls: React.ReactNode; footer: React.ReactNode; finalDiff?: string | null;
}) {
  const [tab, setTab] = useState<Tab>("investigation");
  const story = useMemo(() => buildStory(events, now, meta), [events, now, meta]);
  const groups = useMemo(() => groupStory(story, now), [story, now]);
  const done = story.entries.find((e) => e.kind === "done");
  const state = done ? (done.verified ? "verified" : "unresolved") : "running";
  const verification = story.entries.find((e) => e.kind === "verify");
  const report = verification?.kind === "verify" ? verification.report : null;
  const rootCause = story.entries.find((e) => e.kind === "verdict" && e.rootCause);
  const fixes = story.entries.filter((e) => e.kind === "fix");
  const reduction = story.before && story.after !== null ? (1 - story.after / story.before) * 100 : null;
  const patch = done?.verified ? finalDiff ?? done.diff : null;

  return (
    <main id="main-content">
      <header className="title-row">
        <div><h1>{title}</h1><p className="endpoint"><code>{meta.endpoint || "Waiting for endpoint"}</code></p></div>
        <div className="run-state">{controls}</div>
      </header>

      <div className="investigation-layout">
        <div className="work-pane">
          <nav className="tabs" aria-label="Investigation views">
            <button aria-current={tab === "investigation" ? "page" : undefined} onClick={() => setTab("investigation")}>Investigation</button>
            <button aria-current={tab === "patch" ? "page" : undefined} onClick={() => setTab("patch")}>Code patch</button>
          </nav>

          {tab === "investigation" ? <>
            <Steps groups={groups} story={story} now={now} endpoint={meta.endpoint} />
            {fixes.length > 0 && <details className="candidate-details">
              <summary>Compare {fixes.length} fixes{fixes.some((fix) => fix.status === "rejected") && <span>{fixes.filter((fix) => fix.status === "rejected").length} rejected</span>}</summary>
              <div className="table-scroll"><table>
                <thead><tr><th>Proposed fix</th><th>p99 latency</th><th>Tests</th><th>Result</th></tr></thead>
                <tbody>{fixes.map((fix) => <tr key={fix.id}>
                  <td><code>{fix.name}</code></td>
                  <td className="numeric">{fix.p99 !== null ? formatMs(fix.p99) : "—"}</td>
                  <td>{fix.tests ?? "Pending"}</td>
                  <td><span className={`candidate-status c-${fix.status}`}>{({ winner: "Selected", valid: "Passed", rejected: "Rejected", waiting: "Waiting", running: "Running" })[fix.status]}</span></td>
                </tr>)}</tbody>
              </table></div>
            </details>}
          </> : <section className="patch-panel">
            {patch ? <>
              <div className="patch-heading"><code>{done?.winner}</code><span>Awaiting approval</span></div>
              <DiffView diff={patch} />
            </> : <div className="empty-state">
              <h2>{state === "unresolved" ? "No patch ready for review" : "Waiting for a verified patch"}</h2>
              <p>{done?.reason ?? "The patch appears here once the fix passes correctness tests and performance verification."}</p>
            </div>}
          </section>}
        </div>

        <aside className="measurement-pane" aria-label="Run measurements">
          <h2>Latency <span>p99</span></h2>
          <div className="metric-pair">
            <div className="metric"><span>Before</span><strong>{story.before !== null ? formatMs(story.before) : "—"}</strong></div>
            <div className="metric improved"><span>After</span><strong>{story.after !== null ? formatMs(story.after) : "—"}</strong></div>
          </div>
          {reduction !== null && <p className="improvement-label">{reduction.toFixed(1)}% lower latency</p>}
          <dl className="measurement-facts">
            <div><dt>Target</dt><dd>&lt; {formatMs(story.target)}</dd></div>
            <div><dt>Tests</dt><dd>{report?.candidate.tests_total != null ? `${report.candidate.tests_passed}/${report.candidate.tests_total} passed` : "Pending"}</dd></div>
          </dl>
          <section className="finding">
            <h3>Root cause</h3>
            <p>{rootCause?.kind === "verdict" ? rootCause.hypothesis : state === "unresolved" ? "No cause confirmed." : "Investigating."}</p>
          </section>
          {state === "unresolved" && <p className="stop-reason">{done?.reason ?? "No verified fix."}</p>}
        </aside>
      </div>
      {footer && <footer className="footnote">{footer}</footer>}
    </main>
  );
}

function SavedView({ run }: { run: Run }) {
  const now = run.events.length ? Date.parse(run.events.at(-1)!.at) - Date.parse(run.events[0].at) : 0;
  const meta = useMemo<Meta>(() => ({ endpoint: run.objective?.endpoint ?? "", service: run.service, target: run.objective?.target ?? 0, candidates: run.candidates }), [run]);
  const footer = run.actions_url && <a href={run.actions_url} target="_blank" rel="noreferrer">Execution log</a>;
  return <Investigation title={TITLES[run.scenario ?? ""] ?? run.service} events={run.events} meta={meta} now={now}
    controls={null} footer={footer} />;
}

function LocalLiveView() {
  const feed = useLiveFeed(true);
  const baseline = feed.events.find((e) => e.kind === "baseline")?.message ?? "";
  const meta = useMemo<Meta>(() => ({ endpoint: baseline.split(" p99")[0], service: feed.id?.replace(/^\d{8}-\d{6}-/, "") ?? "", target: Number(baseline.match(/target < ([\d.]+)ms/)?.[1] ?? 100), candidates: [] }), [baseline, feed.id]);
  if (!feed.events.length) return <main id="main-content" className="live-waiting">
    <h1>Live investigation</h1>
    <p role="status">{feed.state === "error" ? "Live server is offline. Start it from the project directory." : feed.state === "waiting" ? "Connected. Waiting for an investigation to start." : "Connecting to the live server…"}</p>
    <details className="setup-details" open={feed.state === "error"}><summary>Start an investigation</summary>
    <div className="live-commands">
      <div><span>1. Start the live server</span><code>uv run hotpath serve</code></div>
      <div><span>2. Start an investigation in another terminal</span><code>uv run hotpath investigate examples/checkout-service</code></div>
    </div>
    <p className="setup-note">Uses your configured Nemotron model and Nebius API key. Docker must be running. New events appear here automatically.</p></details>
  </main>;
  const label = feed.state === "done" ? "Finished · watching for the next run" : feed.state === "error" ? "Connection interrupted · reconnecting" : `Live · ${clock(feed.now)}`;
  return <Investigation key={feed.id} finalDiff={feed.diff} title={meta.service || "Live investigation"}
    events={feed.events} meta={meta} now={feed.now}
    controls={<span className="clock live-clock" role="status">{label}</span>}
    footer={feed.state === "done" ? "Latest completed investigation" : "Following the local investigation"} />;
}

function LiveView() { return HOSTED ? <HostedLiveView /> : <LocalLiveView />; }

const FAILURE_MODES: Record<FailureMode, { label: string; load: string }> = {
  checkout: { label: "Checkout lock contention", load: "650–750 concurrent shoppers" },
  catalog: { label: "Catalog N+1 queries", load: "160–200 concurrent browsers" },
  auth: { label: "Auth event-loop blocking", load: "180–220 readers · 8 logins/s" },
  dashboard: { label: "Dashboard serial queries", load: "5–8 dashboards · 400K orders" },
};

function failureDetails(value: unknown) {
  return FAILURE_MODES[normalizeFailureMode(value)];
}

function HostedLiveView() {
  const feed = useHostedFeed();
  const [failure, setFailure] = useState<FailureMode>("checkout");
  const run = isLegacyCompletedRun(feed.run) ? null : feed.run;
  const running = run && ["queued", "running"].includes(run.state);
  const challenge = run?.challenge;
  const events = useMemo(() => {
    if (!run) return [];
    if (run.state !== "failed" || feed.events.some((e) => ["awaiting_approval", "unresolved", "slo_already_met"].includes(e.phase))) return feed.events;
    return [...feed.events, { at: new Date(run.finished_at ?? Date.now()).toISOString(), phase: "unresolved", kind: "phase",
      message: `Unresolved: ${run.message}`, data: {} }];
  }, [feed.events, run]);
  const meta = useMemo<Meta>(() => ({ endpoint: challenge?.objective.endpoint ?? "", service: challenge?.title ?? "Live investigation",
    target: challenge?.objective.target ?? 100, candidates: [] }), [challenge]);
  const beginning = events.length ? Date.parse(events[0].at) : run?.created_at ?? feed.now;
  const elapsed = Math.max(0, (running ? feed.now : run?.finished_at ?? feed.now) - beginning);
  const selected = FAILURE_MODES[failure];
  const startForm = (compact = false) => <form className={`incident-controls${compact ? " is-compact" : ""}`} onSubmit={(e) => { e.preventDefault(); void feed.start(failure); }}>
    <label className="incident-field">
      <span>Failure profile</span>
      <select value={failure} onChange={(e) => setFailure(e.target.value as FailureMode)}>
        {(Object.entries(FAILURE_MODES) as [FailureMode, (typeof FAILURE_MODES)[FailureMode]][]).map(([value, item]) =>
          <option key={value} value={value}>{item.label}</option>)}
      </select>
      <small>Hidden from the investigator.</small>
    </label>
    <div className="incident-field">
      <span>Workload</span>
      <strong>{selected.load}</strong>
      <small>Fresh data on every run.</small>
    </div>
    <div className="incident-submit">
      <button type="submit" disabled={feed.starting || feed.connection !== "connected"}>
        <span>{feed.starting ? "Starting…" : run ? "Start another run" : "Start live run"}</span>
        <span aria-hidden="true">↗</span>
      </button>
      <small>Results stream into this console.</small>
    </div>
  </form>;
  const connection = feed.connection === "disabled" ? "Live runs are temporarily unavailable." : feed.connection === "offline" ? "Connection interrupted. Reconnecting…" : feed.connection === "connecting" ? "Connecting…" : null;
  const notices = <>
    {connection && <p className="connection-note" role="status">{connection} {feed.connection !== "connecting" && <button className="text-action" onClick={feed.reconnect}>Reconnect</button>}</p>}
    {feed.error && <p className="run-error" role="alert">{feed.error}</p>}
  </>;
  if (!challenge) return <main id="main-content" className="incident-console">
    <header className="console-bar">
      <div><p className="console-kicker">Incident control</p><h1>New live run</h1></div>
    </header>
    <div className="control-workspace">
      <section className="run-config" aria-labelledby="run-config-title">
        <header className="panel-heading"><span>01</span><h2 id="run-config-title">Run configuration</h2></header>
        {feed.connection !== "connected" && <p className="connection-note">{connection} {feed.connection !== "connecting" && <button className="text-action" onClick={feed.reconnect}>Reconnect</button>}</p>}
        {feed.error && <p className="run-error" role="alert">{feed.error}</p>}
        {!running ? startForm() : <div className="dispatch-readout" role="status">
          <div><span>Failure queued</span><strong>{failureDetails(run?.failure).label}</strong></div>
          <div><span>Runner state</span><strong>{run?.message}</strong></div>
          <div><span>Run ID</span><strong>{run?.id.slice(0, 8)}</strong></div>
        </div>}
        {run?.state === "failed" && <p className="run-error">{run.message}</p>}
      </section>
      <section className="run-plan" aria-labelledby="run-plan-title">
        <header className="panel-heading"><span>02</span><h2 id="run-plan-title">Run plan</h2></header>
      <ol>
        <li className={running ? "is-current" : undefined}><span>01</span><strong>Prepare isolated service</strong><small>{running ? "Starting" : "Waiting"}</small></li>
        <li><span>02</span><strong>Measure baseline</strong><small>Waiting</small></li>
        <li><span>03</span><strong>Investigate root cause</strong><small>Waiting</small></li>
        <li><span>04</span><strong>Test candidate fixes</strong><small>Waiting</small></li>
        <li><span>05</span><strong>Verify SLO recovery</strong><small>Waiting</small></li>
      </ol>
      </section>
    </div>
  </main>;
  return <>
    <div className="live-toolbar">
      <span><b>Live incident</b> / {failureDetails(challenge.failure ?? run?.failure ?? challenge.title).label} / {challenge.dataset} / {challenge.concurrency} concurrent users</span>
      {!running && startForm(true)}
    </div>
    {notices}
    <Investigation key={run!.id} title={challenge.title} events={events} meta={meta} now={elapsed}
      finalDiff={run!.diff}
      controls={<span role="status">{run!.state === "failed" ? "Run stopped" : running ? `Live · ${clock(elapsed)}` : "Investigation finished"}</span>}
      footer={run!.execution_url && <a href={run!.execution_url} target="_blank" rel="noreferrer">Execution log</a>} />
  </>;
}

export function App() {
  const [index, setIndex] = useState<RunIndex | null>(null);
  const [current, setCurrent] = useState<string>(HOSTED ? LIVE : parseHash(window.location.hash).run ?? LIVE);
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (HOSTED) return;
    loadIndex().then(setIndex).catch(() => setIndex({ featured: null, runs: [] }));
    const onHash = () => {
      if (window.location.hash !== "#main-content") setCurrent(parseHash(window.location.hash).run ?? LIVE);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  useEffect(() => {
    if (current === LIVE) { setError(null); return; }
    let active = true;
    setRun(null); setError(null);
    loadRun(current).then((data) => { if (active) setRun(data); }).catch((e: Error) => { if (active) setError(e.message); });
    return () => { active = false; };
  }, [current]);
  return <div className="app-shell">
    <a href="#main-content" className="skip-link">Skip to content</a>
    <header className="demo-header">
      <div className="demo-header-inner">
        <a className="logo" href={formatHash({ run: LIVE })}><span aria-hidden="true" />HotPath</a>
      <nav className="demo-services" aria-label="Investigations">
        <a href={formatHash({ run: LIVE })} aria-current={current === LIVE ? "page" : undefined}><strong>Live</strong></a>
        {!HOSTED && !!index?.runs.length && <details className="history-menu">
          <summary>Past runs</summary>
          <div>{index.runs.map((r) => (
            <a key={r.id} href={formatHash({ run: r.id })} aria-current={current === r.id ? "page" : undefined}>
              <strong>{r.service.replace(/-service$/, "")}</strong><span>{r.id.slice(0, 8)}</span>
            </a>
          ))}</div>
        </details>}
      </nav>
        <div className="header-actions">
          <a className="source-link" href={REPO_URL} target="_blank" rel="noreferrer">GitHub</a>
          {!HOSTED && <a className="source-link" href={`${REPO_URL}#live-demo`} target="_blank" rel="noreferrer">Setup</a>}
        </div>
      </div>
    </header>
    <div className="page">

      {current === LIVE ? <LiveView /> : error ? <main id="main-content" className="empty-state" role="alert"><h1>Unable to load this run</h1><p>{error}</p><button className="secondary" onClick={() => window.location.reload()}>Try again</button></main> : run ? <SavedView key={run.id} run={run} /> : <main id="main-content" className="loading-state" role="status"><span className="icon spin" />Loading investigation…</main>}
    </div>
  </div>;
}
