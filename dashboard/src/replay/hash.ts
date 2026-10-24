export interface Location {
  run?: string;
  step?: string;
}

export function parseHash(hash: string): Location {
  const params = new URLSearchParams(hash.replace(/^#/, ""));
  const out: Location = {};
  const run = params.get("run");
  const step = params.get("step");
  if (run) out.run = run;
  if (step) out.step = step;
  return out;
}

export function formatHash({ run, step }: Location): string {
  const params = new URLSearchParams();
  if (run) params.set("run", run);
  if (step) params.set("step", step);
  return `#${params.toString()}`;
}
