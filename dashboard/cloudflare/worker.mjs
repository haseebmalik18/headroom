export { LiveDemo } from "./coordinator.mjs";
import { DAILY_RUNS, json } from "./shared.mjs";
export { DAILY_RUNS, json } from "./shared.mjs";
const enabled = (env) => env.LIVE_ENABLED === "true" && !!env.GITHUB_DISPATCH_TOKEN && !!env.DEMO_CALLBACK_SECRET;

async function matchesSecret(supplied, expected) {
  if (!supplied || !expected) return false;
  const hash = (s) => crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  const [a, b] = await Promise.all([hash(supplied), hash(`Bearer ${expected}`)]);
  const x = new Uint8Array(a), y = new Uint8Array(b);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/api/status" && request.method === "GET") {
      return json({ service: "headroom", hosting: "cloudflare", live: { enabled: enabled(env), daily_runs: DAILY_RUNS } });
    }
    if (["/api/demo", "/api/demo/start", "/api/demo/socket", "/api/demo/update"].includes(url.pathname)) {
      if (!enabled(env)) return json({ error: "Live runs are temporarily unavailable." }, 503);
      if (url.pathname === "/api/demo/update") {
        if (request.method !== "POST") return json({ error: "Method not allowed" }, 405);
        if (!await matchesSecret(request.headers.get("Authorization"), env.DEMO_CALLBACK_SECRET)) return json({ error: "Unauthorized" }, 401);
      } else if (url.pathname === "/api/demo/start" || url.pathname === "/api/demo/socket") {
        if (request.headers.get("Origin") !== url.origin) return json({ error: "Origin not allowed" }, 403);
      }
      return env.LIVE_DEMO.get(env.LIVE_DEMO.idFromName("public-demo")).fetch(request);
    }
    if (url.pathname === "/api" || url.pathname.startsWith("/api/")) return json({ error: "Not found" }, 404);
    return env.ASSETS.fetch(request);
  },
};
