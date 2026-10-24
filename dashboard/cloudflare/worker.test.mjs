import assert from "node:assert/strict";
import { test } from "node:test";
import worker from "./worker.mjs";
import { LiveDemo } from "./coordinator.mjs";

test("status reports hosting separately from live execution", async () => {
  const response = await worker.fetch(new Request("https://demo.example/api/status"), {});
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), {
    service: "headroom", hosting: "cloudflare", live: { enabled: false, daily_runs: 3 },
  });
});

test("API paths never fall through to the HTML shell or simulate live execution", async () => {
  for (const [path, status] of [["/api/live?id=latest", 404], ["/api/investigations", 404], ["/api/missing", 404]]) {
    const response = await worker.fetch(new Request(`https://demo.example${path}`), {});
    assert.equal(response.status, status);
    assert.match(response.headers.get("Content-Type"), /application\/json/);
  }
  const post = await worker.fetch(new Request("https://demo.example/api/status", { method: "POST" }), {});
  assert.equal(post.status, 404);
});

test("asset fallback preserves the request", async () => {
  const request = new Request("https://demo.example/runs/index.json");
  const response = await worker.fetch(request, { ASSETS: {
    fetch: async (received) => {
      assert.equal(received, request);
      return new Response("asset");
    },
  } });
  assert.equal(await response.text(), "asset");
});

class MemoryStorage {
  constructor() { this.data = new Map(); this.alarm = null; }
  async get(key) { return this.data.get(key); }
  async put(key, value) {
    if (typeof key === "object") for (const [name, item] of Object.entries(key)) this.data.set(name, item);
    else this.data.set(key, value);
  }
  async list({ prefix = "" } = {}) {
    return new Map([...this.data.entries()].filter(([key]) => key.startsWith(prefix)).sort());
  }
  async delete(keys) {
    for (const key of Array.isArray(keys) ? keys : [keys]) this.data.delete(key);
  }
  async setAlarm(value) { this.alarm = value; }
  async deleteAlarm() { this.alarm = null; }
}

const update = (demo, payload) => demo.fetch(new Request("https://demo.example/api/demo/update", {
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
}));

test("a reserved run is claimed once and keeps an ordered live event log", async (t) => {
  const storage = new MemoryStorage();
  const ctx = { storage, getWebSockets: () => [] };
  const env = {
    DEMO_CALLBACK_SECRET: "s".repeat(40), GITHUB_DISPATCH_TOKEN: "token",
    GITHUB_REPOSITORY: "owner/repo", GITHUB_REF: "main",
  };
  const demo = new LiveDemo(ctx, env);
  const dispatches = [];
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async (request, options) => { dispatches.push([request, JSON.parse(options.body)]); return new Response(null, { status: 204 }); };
  t.after(() => { globalThis.fetch = originalFetch; });

  const rejected = await demo.fetch(new Request("https://demo.example/api/demo/start", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{\"failure\":\"visitor-command\"}",
  }));
  assert.equal(rejected.status, 400);
  assert.equal(dispatches.length, 0);

  const request = () => new Request("https://demo.example/api/demo/start", {
    method: "POST", headers: { "Content-Type": "application/json", "CF-Connecting-IP": "192.0.2.1" }, body: "{\"failure\":\"auth\"}",
  });
  const started = await demo.fetch(request());
  assert.equal(started.status, 202);
  const run = (await started.json()).run;
  assert.equal(dispatches.length, 1);
  assert.deepEqual(dispatches[0][1].inputs, { run_id: run.id, seed: String(run.seed), failure: "auth" });

  const joined = await demo.fetch(request());
  assert.equal((await joined.json()).joined, true);
  assert.equal(dispatches.length, 1);
  assert.equal((await update(demo, { type: "claim", run_id: run.id, invocation: "123:1", seed: run.seed })).status, 200);
  assert.equal((await update(demo, { type: "claim", run_id: run.id, invocation: "124:1", seed: run.seed })).status, 409);

  const event = { at: "2026-10-24T12:00:00Z", phase: "baseline", kind: "phase", message: "Measuring", data: {} };
  assert.equal((await update(demo, { type: "event", run_id: run.id, invocation: "123:1", sequence: 0, event })).status, 200);
  assert.equal((await update(demo, { type: "event", run_id: run.id, invocation: "123:1", sequence: 0, event })).status, 200);
  assert.equal((await update(demo, { type: "finish", run_id: run.id, invocation: "123:1", state: "done", diff: "patch" })).status, 200);
  const snapshot = await demo.snapshot();
  assert.equal(snapshot.run.state, "done");
  assert.equal(snapshot.run.diff, "patch");
  assert.deepEqual(snapshot.events, [event]);
});

test("the public router enforces same-origin starts and authenticated runner updates", async () => {
  const calls = [];
  const env = {
    LIVE_ENABLED: "true", GITHUB_DISPATCH_TOKEN: "token", DEMO_CALLBACK_SECRET: "s".repeat(40),
    LIVE_DEMO: { idFromName: (name) => name, get: () => ({ fetch: async (request) => { calls.push(request); return new Response("ok"); } }) },
  };
  const crossOrigin = await worker.fetch(new Request("https://demo.example/api/demo/start", {
    method: "POST", headers: { Origin: "https://attacker.example" },
  }), env);
  assert.equal(crossOrigin.status, 403);
  const unauthorized = await worker.fetch(new Request("https://demo.example/api/demo/update", { method: "POST" }), env);
  assert.equal(unauthorized.status, 401);
  const accepted = await worker.fetch(new Request("https://demo.example/api/demo/update", {
    method: "POST", headers: { Authorization: `Bearer ${env.DEMO_CALLBACK_SECRET}` },
  }), env);
  assert.equal(accepted.status, 200);
  assert.equal(calls.length, 1);
});
