import type { Run, RunIndex } from "./types";

async function getJson<T>(path: string, what: string): Promise<T> {
  const response = await fetch(`${import.meta.env.BASE_URL}runs/${path}`);
  if (!response.ok) throw new Error(`Could not load ${what}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

export const loadIndex = () => getJson<RunIndex>("index.json", "the list of runs");

export const loadRun = (id: string) => getJson<Run>(`${encodeURIComponent(id)}.json`, `run ${id}`);
