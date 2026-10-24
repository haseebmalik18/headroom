import { useEffect, useReducer, useState } from "react";
import type { RunEvent } from "../data/types";

export type FailureMode = "checkout" | "catalog" | "auth" | "dashboard" | "pricing";

export function normalizeFailureMode(value: unknown): FailureMode {
  if (typeof value !== "string") return "checkout";
  const name = value.toLowerCase();
  if (name.includes("checkout") || name.includes("lock-contention")) return "checkout";
  if (name.includes("catalog") || name.includes("n-plus-one")) return "catalog";
  if (name.includes("auth") || name.includes("event-loop") || name.includes("blocking")) return "auth";
  if (name.includes("dashboard") || name.includes("sequential")) return "dashboard";
  if (name.includes("pricing") || name.includes("stampede")) return "pricing";
  return "checkout";
}

export interface LiveRun {
  id: string; seed: number; state: "queued" | "running" | "done" | "failed";
  failure?: string;
  created_at: number; finished_at?: number; message: string;
  execution_url: string | null; diff: string | null;
  challenge: { title: string; dataset: string; failure?: string; concurrency: number; fingerprint: string;
    objective: { endpoint: string; target: number } } | null;
}

export function isLegacyCompletedRun(run: LiveRun | null): boolean {
  return !!run && ["done", "failed"].includes(run.state) && !run.failure && !run.challenge?.failure;
}

export interface LiveSnapshot { run: LiveRun | null; events: RunEvent[] }
export type LiveFrame =
  | ({ type: "snapshot" } & LiveSnapshot)
  | { type: "state"; run: LiveRun }
  | { type: "event"; run: LiveRun; sequence: number; event: RunEvent };

export function receive(snapshot: LiveSnapshot, frame: LiveFrame): LiveSnapshot {
  if (frame.type === "snapshot") return { run: frame.run, events: frame.events };
  if (frame.run.id !== snapshot.run?.id) throw new Error("Run changed; reconnect.");
  if (frame.type === "state") return { ...snapshot, run: frame.run };
  if (frame.sequence < snapshot.events.length) return snapshot;
  if (frame.sequence !== snapshot.events.length) throw new Error("Event gap; reconnect.");
  return { run: frame.run, events: [...snapshot.events, frame.event] };
}

export function useHostedFeed() {
  const [snapshot, setSnapshot] = useState<LiveSnapshot>({ run: null, events: [] });
  const [connection, setConnection] = useState<"connecting" | "connected" | "offline" | "disabled">("connecting");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, reconnect] = useReducer((n: number) => n + 1, 0);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout>;
    let retry = 1000;
    let current: LiveSnapshot = { run: null, events: [] };
    const controller = new AbortController();
    const connect = () => {
      if (disposed || document.hidden) return;
      const url = new URL("/api/demo/socket", location.href);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      const next = new WebSocket(url);
      socket = next;
      next.onmessage = (message) => {
        if (disposed) return;
        try {
          current = receive(current, JSON.parse(message.data) as LiveFrame);
          setSnapshot(current); setConnection("connected"); retry = 1000;
        } catch { next.close(); }
      };
      next.onclose = () => {
        if (disposed || document.hidden) return;
        setConnection("offline");
        timer = setTimeout(connect, retry);
        retry = Math.min(retry * 2, 30_000);
      };
      next.onerror = () => next.close();
    };
    const visibility = () => {
      clearTimeout(timer); socket?.close();
      if (!document.hidden) reconnect();
    };
    document.addEventListener("visibilitychange", visibility);
    const timeout = setTimeout(() => controller.abort(), 10_000);
    void fetch("/api/status", { signal: controller.signal, cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw new Error("Status unavailable");
      const status = await response.json();
      if (disposed) return;
      if (!status.live?.enabled) { setConnection("disabled"); return; }
      connect();
    }).catch(() => { if (!disposed) setConnection("offline"); }).finally(() => clearTimeout(timeout));
    return () => {
      disposed = true; clearTimeout(timer); clearTimeout(timeout);
      controller.abort(); socket?.close();
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [revision]);

  useEffect(() => {
    if (!snapshot.run || !["queued", "running"].includes(snapshot.run.state)) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [snapshot.run?.id, snapshot.run?.state]);

  const start = async (failure: FailureMode) => {
    if (starting) return;
    setStarting(true); setError(null);
    try {
      const response = await fetch("/api/demo/start", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ failure }),
        signal: AbortSignal.timeout(20_000),
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error ?? "Could not start the run.");
      // Resume the authoritative log; never retry a start on an ambiguous timeout.
      reconnect();
    } catch (error) {
      setError(error instanceof Error && error.name !== "TimeoutError" ? error.message : "The request timed out. Reconnect to check whether the run started.");
    } finally { setStarting(false); }
  };
  return { ...snapshot, connection, starting, error, start, reconnect, now };
}
