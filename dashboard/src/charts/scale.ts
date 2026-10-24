export type Scale = (v: number) => number;

export const linearScale = ([d0, d1]: [number, number], [r0, r1]: [number, number]): Scale =>
  (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

export const logScale = ([d0, d1]: [number, number], [r0, r1]: [number, number]): Scale => {
  const l0 = Math.log10(d0);
  const l1 = Math.log10(d1);
  return (v) => r0 + ((Math.log10(Math.max(v, d0)) - l0) / (l1 - l0 || 1)) * (r1 - r0);
};

/** The smallest of 1, 1.5, 2, 2.5, 4, 5, 8, 10 x 10^k that is >= v. */
export function niceMax(v: number): number {
  if (v <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(v));
  const step = [1, 1.5, 2, 2.5, 4, 5, 8, 10].find((s) => s * power >= v - 1e-9)!;
  return Math.round(step * power * 1e6) / 1e6;
}

export const linearTicks = (max: number, count = 4): number[] =>
  Array.from({ length: count + 1 }, (_, i) => (max / count) * i);

export function logTicks(min: number, max: number): number[] {
  const ticks = [];
  for (let p = Math.floor(Math.log10(min)); p <= Math.ceil(Math.log10(max)); p++) ticks.push(10 ** p);
  return ticks;
}

/** A value axis for latency: log when the values span more than 10x, so 5 ms and 2,450 ms both read. */
export function valueScale(values: number[], range: [number, number]) {
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  if (lo > 0 && hi / lo > 10) {
    const ticks = logTicks(lo, hi);
    const domain: [number, number] = [ticks[0], ticks.at(-1)!];
    return { log: true, scale: logScale(domain, range), ticks, domain };
  }
  const max = niceMax(hi);
  return { log: false, scale: linearScale([0, max], range), ticks: linearTicks(max), domain: [0, max] as [number, number] };
}

export function formatMs(v: number): string {
  if (v >= 1000) return `${Math.round(v).toLocaleString("en-US")} ms`;
  if (v >= 100 || Number.isInteger(v)) return `${Math.round(v)} ms`;
  return `${v.toFixed(1)} ms`;
}

export const formatTick = (v: number) => (v >= 1000 ? `${v / 1000}s` : `${v}`);
