import { DAILY_RUNS, json } from "./shared.mjs";

const QUEUE_MS = 10 * 60_000;
const RUN_MS = 65 * 60_000;
const active = (run) => run && ["queued", "running"].includes(run.state);

async function body(request, limit) {
  if (!request.headers.get("Content-Type")?.startsWith("application/json")) throw new Error("Send JSON.");
  const reader = request.body?.getReader();
  let size = 0, text = "";
  const decoder = new TextDecoder();
  if (reader) while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    size += value.length;
    if (size > limit) { await reader.cancel(); throw new Error("Request too large."); }
    text += decoder.decode(value, { stream: true });
  }
  return JSON.parse(text + decoder.decode());
}

/** A shared, durable run reservation and event log. Sockets hibernate when idle.
 * Only the current live buffer is retained; GitHub artifacts keep past evidence. */
export class LiveDemo {
  constructor(ctx, env) { this.ctx = ctx; this.env = env; }

  async fetch(request) {
    const path = new URL(request.url).pathname;
    if (path === "/api/demo" && request.method === "GET") return json(await this.snapshot());
    if (path === "/api/demo/socket" && request.method === "GET") {
      if (request.headers.get("Upgrade")?.toLowerCase() !== "websocket") return json({ error: "Expected WebSocket" }, 426);
      if (this.ctx.getWebSockets().length >= 100) return json({ error: "The live audience is full. Try again shortly." }, 429);
      const pair = new WebSocketPair();
      this.ctx.acceptWebSocket(pair[1]);
      pair[1].send(JSON.stringify({ type: "snapshot", ...await this.snapshot() }));
      return new Response(null, { status: 101, webSocket: pair[0] });
    }
    if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);
    let data;
    try { data = await body(request, path === "/api/demo/update" ? 110_000 : 1024); }
    catch { return json({ error: "Invalid or oversized JSON request." }, 400); }
    if (!data || typeof data !== "object" || Array.isArray(data)) return json({ error: "Expected an object." }, 400);
    if (path === "/api/demo/start") return this.start(data, request);
    if (path === "/api/demo/update") return this.update(data);
    return json({ error: "Not found" }, 404);
  }

  async snapshot() {
    const run = await this.ctx.storage.get("run") ?? null;
    const events = [...(await this.ctx.storage.list({ prefix: "event:" })).values()];
    return { run, events, daily_runs: DAILY_RUNS };
  }

  broadcast(message) {
    const data = JSON.stringify(message);
    for (const socket of this.ctx.getWebSockets()) {
      try { socket.send(data); } catch { socket.close(1011, "Reconnect to resume"); }
    }
  }

  async start(data, request) {
    if (Object.keys(data).some((key) => key !== "failure") ||
        !["random", "checkout", "catalog", "auth", "dashboard", "pricing"].includes(data.failure ?? "random")) {
      return json({ error: "Choose a supported failure mode." }, 400);
    }
    const now = Date.now();
    let run = await this.ctx.storage.get("run");
    if (active(run)) return json({ run, joined: true });
    const today = new Date(now).toISOString().slice(0, 10);
    let usage = await this.ctx.storage.get("usage");
    if (usage?.day !== today) usage = { day: today, count: 0, visitors: {} };
    if (usage.count >= DAILY_RUNS) return json({ error: "Today's live runs are used. New runs open at midnight UTC." }, 429);
    const bytes = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(
      `${this.env.DEMO_CALLBACK_SECRET}:${request.headers.get("CF-Connecting-IP") ?? "local"}`,
    ));
    const visitor = Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, "0")).join("");
    if (now - (usage.visitors[visitor] ?? 0) < 10 * 60_000) return json({ error: "Please wait ten minutes between new runs." }, 429);
    usage.count++;
    usage.visitors[visitor] = now;
    run = {
      id: crypto.randomUUID(), seed: crypto.getRandomValues(new Uint32Array(1))[0], failure: data.failure ?? "random",
      state: "queued", created_at: now, deadline: now + QUEUE_MS, count: 0, bytes: 0,
      challenge: null, diff: null, message: "Waiting for a GitHub runner…", execution_url: null,
    };
    const keys = [...(await this.ctx.storage.list({ prefix: "event:" })).keys()];
    for (let i = 0; i < keys.length; i += 128) await this.ctx.storage.delete(keys.slice(i, i + 128));
    await this.ctx.storage.put({ run, usage });
    await this.ctx.storage.setAlarm(run.deadline);
    this.broadcast({ type: "snapshot", run, events: [], daily_runs: DAILY_RUNS });
    try {
      const response = await fetch(`https://api.github.com/repos/${this.env.GITHUB_REPOSITORY}/actions/workflows/live-demo.yml/dispatches`, {
        method: "POST", signal: AbortSignal.timeout(10_000),
        headers: {
          Authorization: `Bearer ${this.env.GITHUB_DISPATCH_TOKEN}`, "Content-Type": "application/json",
          Accept: "application/vnd.github+json", "User-Agent": "HotPath-demo", "X-GitHub-Api-Version": "2022-11-28",
        },
        body: JSON.stringify({ ref: this.env.GITHUB_REF, inputs: {
          run_id: run.id, seed: String(run.seed), failure: run.failure,
        } }),
      });
      if (!response.ok) {
        const current = await this.ctx.storage.get("run");
        if (current?.id === run.id && active(current) && !current.invocation) {
          await this.finish(current, "failed", "GitHub could not start this run. Please try again later.");
        }
      }
    } catch {
      // A lost response might still mean a successful dispatch. Never retry it.
      const current = await this.ctx.storage.get("run");
      if (current?.id === run.id && active(current) && !current.invocation) {
        current.message = "Waiting for GitHub to confirm the run…";
        await this.ctx.storage.put("run", current);
        this.broadcast({ type: "state", run: current });
      }
    }
    run = await this.ctx.storage.get("run");
    return json({ run }, run.state === "failed" ? 502 : 202);
  }

  async update(data) {
    const run = await this.ctx.storage.get("run");
    if (!run || data.run_id !== run.id) return json({ error: "Run no longer active" }, 409);
    if (Date.now() >= run.deadline && active(run)) await this.finish(run, "failed", "The runner timed out. No result was verified.");
    if (!active(run)) {
      if (data.type === "finish" && data.invocation === run.invocation) return json({ accepted: true });
      return json({ error: "Run has ended" }, 409);
    }
    if (data.type === "claim") {
      if (!/^\d+:\d+$/.test(data.invocation) || !Number.isInteger(data.seed) || data.seed !== run.seed) return json({ error: "Invalid claim" }, 400);
      if (run.invocation && data.invocation !== run.invocation) return json({ error: "Run already claimed" }, 409);
      if (!run.invocation) {
        run.invocation = data.invocation;
        run.state = "running";
        run.deadline = Date.now() + RUN_MS;
        run.execution_url = `https://github.com/${this.env.GITHUB_REPOSITORY}/actions/runs/${data.invocation.split(":")[0]}`;
        run.message = "Preparing a fresh benchmark case…";
        await this.ctx.storage.put("run", run);
        await this.ctx.storage.setAlarm(run.deadline);
        this.broadcast({ type: "state", run });
      }
      return json({ accepted: true });
    }
    if (data.type === "setup_failed" && !run.invocation) {
      await this.finish(run, "failed", "The GitHub runner could not start. No result was verified.");
      return json({ accepted: true });
    }
    if (!run.invocation || data.invocation !== run.invocation) return json({ error: "Claim the run first" }, 409);
    if (data.type === "event") {
      if (!Number.isInteger(data.sequence) || data.sequence < 0) return json({ error: "Invalid sequence" }, 400);
      if (data.sequence < run.count) return json({ accepted: true });
      if (data.sequence !== run.count) return json({ error: "Event gap" }, 409);
      const event = data.event;
      if (!event || typeof event.kind !== "string" || typeof event.phase !== "string" ||
          typeof event.message !== "string" || typeof event.at !== "string" ||
          !Number.isFinite(Date.parse(event.at))) return json({ error: "Invalid event" }, 400);
      const size = new TextEncoder().encode(JSON.stringify(event)).length;
      if (size > 96_000 || run.count >= 3000 || run.bytes + size > 6_000_000) return json({ error: "Live buffer full" }, 413);
      if (event.kind === "challenge") run.challenge = event.data;
      run.count++;
      run.bytes += size;
      run.message = event.message;
      await this.ctx.storage.put({ [`event:${String(data.sequence).padStart(6, "0")}`]: event, run });
      this.broadcast({ type: "event", run, sequence: data.sequence, event });
      return json({ accepted: true });
    }
    if (data.type === "finish") {
      if (!["done", "failed"].includes(data.state) || (data.diff != null && typeof data.diff !== "string")) return json({ error: "Invalid outcome" }, 400);
      if (data.diff && new TextEncoder().encode(data.diff).length > 96_000) return json({ error: "Patch too large" }, 413);
      run.diff = data.state === "done" ? data.diff ?? null : null;
      await this.finish(run, data.state, data.state === "done" ? "Investigation finished" : "The runner stopped. No result was verified.");
      return json({ accepted: true });
    }
    return json({ error: "Invalid update" }, 400);
  }

  async finish(run, state, message) {
    Object.assign(run, { state, message, finished_at: Date.now() });
    await this.ctx.storage.put("run", run);
    await this.ctx.storage.deleteAlarm();
    this.broadcast({ type: "state", run });
  }

  async alarm() {
    const run = await this.ctx.storage.get("run");
    if (active(run)) await this.finish(run, "failed", "The runner timed out. No result was verified.");
  }
  webSocketMessage(socket) { socket.close(1008, "This connection is read-only"); }
  webSocketClose(socket, code, reason) { socket.close(code, reason); }
  webSocketError(socket) { socket.close(1011, "Reconnect to resume"); }
}
