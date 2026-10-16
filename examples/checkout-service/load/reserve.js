// Load test for POST /inventory/reserve.
//
// Models VUS concurrent shoppers. Each one reserves a random catalog item,
// then "thinks" for ~THINK_MS (uniformly 0.5x-1.5x) before the next request.
// Shoppers start staggered across one think period so they never arrive in
// lockstep. Only requests sent after WARMUP, during DURATION, are reported.
//
// Env: BASE_URL, VUS, WARMUP, DURATION, THINK_MS, SKU_COUNT, LABEL

import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const VUS = parseInt(__ENV.VUS || '100', 10);
const WARMUP = __ENV.WARMUP || '10s';
const DURATION = __ENV.DURATION || '30s';
const THINK_MS = parseFloat(__ENV.THINK_MS || '500');
const SKU_COUNT = parseInt(__ENV.SKU_COUNT || '1000', 10);
const LABEL = __ENV.LABEL || `vus-${VUS}`;

function seconds(duration) {
  const m = /^(\d+(?:\.\d+)?)(ms|s|m)$/.exec(duration);
  const value = parseFloat(m[1]);
  return m[2] === 'ms' ? value / 1000 : m[2] === 'm' ? value * 60 : value;
}

const WARMUP_MS = seconds(WARMUP) * 1000;
const MEASURE_END_MS = WARMUP_MS + seconds(DURATION) * 1000;

const latency = new Trend('reserve_latency', true);
const errors = new Rate('reserve_errors');
const requests = new Counter('reserve_requests');

export const options = {
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  scenarios: {
    shoppers: {
      executor: 'constant-vus',
      vus: VUS,
      duration: `${MEASURE_END_MS / 1000}s`,
      gracefulStop: '10s',
    },
  },
};

const params = { headers: { 'Content-Type': 'application/json' }, tags: { name: 'reserve' } };

function think() {
  sleep((THINK_MS / 1000) * (0.5 + Math.random()));
}

export default function () {
  if (exec.vu.iterationInScenario === 0) {
    sleep((THINK_MS / 1000) * Math.random());
  }

  const n = 1 + Math.floor(Math.random() * SKU_COUNT);
  const sku = `SKU-${String(n).padStart(5, '0')}`;
  const sentAt = exec.instance.currentTestRunDuration;
  const res = http.post(`${BASE_URL}/inventory/reserve`, JSON.stringify({ sku, quantity: 1 }), params);

  if (sentAt >= WARMUP_MS && sentAt < MEASURE_END_MS) {
    latency.add(res.timings.duration);
    errors.add(res.status !== 201);
    requests.add(1);
  }
  think();
}

export function handleSummary(data) {
  const t = data.metrics.reserve_latency.values;
  const count = data.metrics.reserve_requests ? data.metrics.reserve_requests.values.count : 0;
  const result = {
    label: LABEL,
    vus: VUS,
    think_ms: THINK_MS,
    duration_s: seconds(DURATION),
    requests: count,
    p50_ms: +t.med.toFixed(2),
    p95_ms: +t['p(95)'].toFixed(2),
    p99_ms: +t['p(99)'].toFixed(2),
    max_ms: +t.max.toFixed(2),
    avg_ms: +t.avg.toFixed(2),
    throughput_rps: +(count / seconds(DURATION)).toFixed(1),
    error_rate: +data.metrics.reserve_errors.values.rate.toFixed(5),
  };
  const line =
    `[${LABEL}] vus=${VUS} rps=${result.throughput_rps} ` +
    `p50=${result.p50_ms}ms p95=${result.p95_ms}ms p99=${result.p99_ms}ms ` +
    `errors=${(result.error_rate * 100).toFixed(2)}%\n`;
  return {
    stdout: line,
    [`/results/k6-${LABEL}.json`]: JSON.stringify(result, null, 2),
  };
}
