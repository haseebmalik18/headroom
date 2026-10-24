/** What a run is trying to achieve: one metric and its target, mirroring Objective in headroom/config.py. */

const NAMES: Record<string, string> = {
  p50_ms: "p50 latency",
  p95_ms: "p95 latency",
  p99_ms: "p99 latency",
  throughput_rps: "throughput",
  error_rate: "error rate",
};

export const higherIsBetter = (metric: string) => metric === "throughput_rps";

export const metricName = (metric: string) => NAMES[metric] ?? metric;

export function show(metric: string, value: number): string {
  if (metric === "error_rate") return `${Number((value * 100).toFixed(3))}%`;
  if (metric === "throughput_rps") return `${Math.round(value).toLocaleString("en-US")} req/s`;
  return value >= 100 ? `${Math.round(value).toLocaleString("en-US")} ms` : `${value.toFixed(1)} ms`;
}

/** The target on its own, e.g. "under 100 ms" or "at least 240 req/s". */
export function targetText(metric: string, target: number): string {
  if (higherIsBetter(metric)) return `at least ${show(metric, target)}`;
  return metric === "error_rate" ? `under ${show(metric, target)}` : `under ${Math.round(target)} ms`;
}

export function goalText(metric: string, target: number): string {
  return `${metricName(metric)}${higherIsBetter(metric) ? " of" : ""} ${targetText(metric, target)}`;
}
