import { useEffect, useRef, useState } from "react";

import type { RunEvent } from "../data/types";

type FeedState = "connecting" | "waiting" | "live" | "done" | "error";

/** Follow real investigations, including runs started after the dashboard was opened. */
export function useLiveFeed(enabled: boolean) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [id, setId] = useState<string | null>(null);
  const [state, setState] = useState<FeedState>("connecting");
  const [now, setNow] = useState(0);
  const [diff, setDiff] = useState<string | null>(null);
  const t0 = useRef<number | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    let current: string | null = null;
    let source: EventSource | null = null;
    let lastEvent = -1;
    let finished = false;
    let timer: ReturnType<typeof setTimeout>;
    let request: AbortController | null = null;

    const connect = (next: string) => {
      source?.close();
      current = next;
      lastEvent = -1;
      finished = false;
      t0.current = null;
      setEvents([]);
      setDiff(null);
      setNow(0);
      setId(next);
      setState("connecting");
      source = new EventSource(`/api/live?id=${encodeURIComponent(next)}`);
      source.onopen = () => setState("live");
      source.onmessage = (message) => {
        const sequence = Number(message.lastEventId);
        if (message.lastEventId && sequence <= lastEvent) return;
        const event = JSON.parse(message.data) as RunEvent;
        if (message.lastEventId) lastEvent = sequence;
        t0.current ??= Date.parse(event.at);
        setEvents((list) => [...list, event]);
        setNow(Math.max(0, Date.now() - t0.current));
        setState("live");
      };
      source.addEventListener("done", (message) => {
        const outcome = JSON.parse((message as MessageEvent).data) as { diff?: string | null };
        setDiff(outcome.diff ?? null);
        finished = true;
        setState("done");
        source?.close();
      });
      source.onerror = () => setState("error"); // EventSource reconnects with Last-Event-ID.
    };

    const discover = async () => {
      request = new AbortController();
      const timeout = setTimeout(() => request?.abort(), 4000);
      try {
        const response = await fetch("/api/investigations", { signal: request.signal, cache: "no-store" });
        if (!response.ok) throw new Error("Live server unavailable");
        const ids: unknown = await response.json();
        if (!Array.isArray(ids) || !ids.every((value) => typeof value === "string")) throw new Error("Invalid live response");
        if (disposed) return;
        if (ids[0] && ids[0] !== current) connect(ids[0]);
        else if (!current) setState("waiting");
        else if (finished) setState("done");
      } catch {
        if (!disposed) setState("error");
      } finally {
        clearTimeout(timeout);
        if (!disposed) timer = setTimeout(discover, 2000);
      }
    };
    void discover();
    return () => {
      disposed = true;
      clearTimeout(timer);
      request?.abort();
      source?.close();
    };
  }, [enabled]);

  useEffect(() => {
    if (!enabled || state !== "live") return;
    const timer = setInterval(() => {
      if (t0.current !== null) setNow(Math.max(0, Date.now() - t0.current));
    }, 250);
    return () => clearInterval(timer);
  }, [enabled, state]);

  const end = events.length ? Date.parse(events.at(-1)!.at) - Date.parse(events[0].at) : 0;
  return { events, id, state, diff, now: state === "done" ? end : Math.max(now, end) };
}
