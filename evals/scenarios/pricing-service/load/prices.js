// Load test for GET /products/{sku}/price during a sale.
//
// VUS concurrent shoppers check prices, pausing ~THINK_MS (uniformly 0.5x-1.5x)
// between requests. 90% of views go to the five bestsellers, the rest spread
// over the catalog. Start times are staggered and only requests sent after
// WARMUP, during DURATION, are reported.
//
// Env: BASE_URL, VUS, WARMUP, DURATION, THINK_MS, PRODUCT_COUNT, LABEL

import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const VUS = parseInt(__ENV.VUS || '100', 10);
const WARMUP = __ENV.WARMUP || '10s';
const DURATION = __ENV.DURATION || '30s';
const THINK_MS = parseFloat(__ENV.THINK_MS || '200');
const PRODUCT_COUNT = parseInt(__ENV.PRODUCT_COUNT || '24', 10);
const LABEL = __ENV.LABEL || `vus-${VUS}`;

function seconds(duration) {
  const m = /^(\d+(?:\.\d+)?)(ms|s|m)$/.exec(duration);
  const value = parseFloat(m[1]);
  return m[2] === 'ms' ? value / 1000 : m[2] === 'm' ? value * 60 : value;
}

const WARMUP_MS = seconds(WARMUP) * 1000;
const MEASURE_END_MS = WARMUP_MS + seconds(DURATION) * 1000;

const latency = new Trend('request_latency', true);
const errors = new Rate('request_errors');
const requests = new Counter('request_count');

export const options = {
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  scenarios: {
    shoppers: { executor: 'constant-vus', vus: VUS, duration: `${MEASURE_END_MS / 1000}s`, gracefulStop: '10s' },
  },
};

export default function () {
  if (exec.vu.iterationInScenario === 0) {
    sleep((THINK_MS / 1000) * Math.random());
  }
  const n = Math.random() < 0.9 ? 1 + Math.floor(Math.random() * 5) : 6 + Math.floor(Math.random() * (PRODUCT_COUNT - 5));
  const sku = `SKU-${String(n).padStart(2, '0')}`;
  const sentAt = exec.instance.currentTestRunDuration;
  const res = http.get(`${BASE_URL}/products/${sku}/price`, { tags: { name: 'price' } });

  if (sentAt >= WARMUP_MS && sentAt < MEASURE_END_MS) {
    latency.add(res.timings.duration);
    errors.add(res.status !== 200);
    requests.add(1);
  }
  sleep((THINK_MS / 1000) * (0.5 + Math.random()));
}

export function handleSummary(data) {
  const t = data.metrics.request_latency.values;
  const count = data.metrics.request_count ? data.metrics.request_count.values.count : 0;
  const result = {
    label: LABEL, vus: VUS, think_ms: THINK_MS, duration_s: seconds(DURATION), requests: count,
    p50_ms: +t.med.toFixed(2), p95_ms: +t['p(95)'].toFixed(2), p99_ms: +t['p(99)'].toFixed(2),
    max_ms: +t.max.toFixed(2), avg_ms: +t.avg.toFixed(2),
    throughput_rps: +(count / seconds(DURATION)).toFixed(1),
    error_rate: +data.metrics.request_errors.values.rate.toFixed(5),
  };
  return {
    stdout: `[${LABEL}] vus=${VUS} rps=${result.throughput_rps} p50=${result.p50_ms}ms p99=${result.p99_ms}ms\n`,
    [`/results/k6-${LABEL}.json`]: JSON.stringify(result, null, 2),
  };
}
