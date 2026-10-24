// Load test for a sale: shoppers check prices and place orders.
//
// VUS concurrent shoppers pause ~THINK_MS (uniformly 0.5x-1.5x) between requests.
// 90% of requests check a price, 10% place an order. 90% of both go to the five
// bestsellers. Start times are staggered and only requests sent after WARMUP,
// during DURATION, are reported, overall and per endpoint.
//
// Env: BASE_URL, VUS, WARMUP, DURATION, THINK_MS, PRODUCT_COUNT, LABEL

import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const VUS = parseInt(__ENV.VUS || '200', 10);
const WARMUP = __ENV.WARMUP || '10s';
const DURATION = __ENV.DURATION || '30s';
const THINK_MS = parseFloat(__ENV.THINK_MS || '200');
const PRODUCT_COUNT = parseInt(__ENV.PRODUCT_COUNT || '24', 10);
const LABEL = __ENV.LABEL || `vus-${VUS}`;
const ORDER_SHARE = 0.1;

function seconds(duration) {
  const m = /^(\d+(?:\.\d+)?)(ms|s|m)$/.exec(duration);
  const value = parseFloat(m[1]);
  return m[2] === 'ms' ? value / 1000 : m[2] === 'm' ? value * 60 : value;
}

const WARMUP_MS = seconds(WARMUP) * 1000;
const MEASURE_END_MS = WARMUP_MS + seconds(DURATION) * 1000;

// The names match the objectives in headroom.yaml.
const ENDPOINTS = {
  price: 'GET /products/{sku}/price',
  order: 'POST /orders',
};
const metrics = { all: { latency: new Trend('request_latency', true), errors: new Rate('request_errors'), count: new Counter('request_count') } };
for (const key of Object.keys(ENDPOINTS)) {
  metrics[key] = {
    latency: new Trend(`latency_${key}`, true),
    errors: new Rate(`errors_${key}`),
    count: new Counter(`count_${key}`),
  };
}

export const options = {
  discardResponseBodies: true,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  scenarios: {
    shoppers: { executor: 'constant-vus', vus: VUS, duration: `${MEASURE_END_MS / 1000}s`, gracefulStop: '10s' },
  },
};

function pickSku() {
  const n = Math.random() < 0.9 ? 1 + Math.floor(Math.random() * 5) : 6 + Math.floor(Math.random() * (PRODUCT_COUNT - 5));
  return `SKU-${String(n).padStart(2, '0')}`;
}

export default function () {
  if (exec.vu.iterationInScenario === 0) {
    sleep((THINK_MS / 1000) * Math.random());
  }
  const sku = pickSku();
  const sentAt = exec.instance.currentTestRunDuration;
  const ordering = Math.random() < ORDER_SHARE;
  const res = ordering
    ? http.post(`${BASE_URL}/orders`, JSON.stringify({ sku, quantity: 1 }),
                { headers: { 'Content-Type': 'application/json' }, tags: { name: 'order' } })
    : http.get(`${BASE_URL}/products/${sku}/price`, { tags: { name: 'price' } });

  if (sentAt >= WARMUP_MS && sentAt < MEASURE_END_MS) {
    // A sold-out product (409) is a correct answer, not an error.
    const failed = ordering ? !(res.status === 201 || res.status === 409) : res.status !== 200;
    for (const m of [metrics.all, metrics[ordering ? 'order' : 'price']]) {
      m.latency.add(res.timings.duration);
      m.errors.add(failed);
      m.count.add(1);
    }
  }
  sleep((THINK_MS / 1000) * (0.5 + Math.random()));
}

function stats(data, latency, errors, count) {
  const t = data.metrics[latency] ? data.metrics[latency].values : null;
  const n = data.metrics[count] ? data.metrics[count].values.count : 0;
  if (!t) return null;
  return {
    requests: n,
    p50_ms: +t.med.toFixed(2), p95_ms: +t['p(95)'].toFixed(2), p99_ms: +t['p(99)'].toFixed(2),
    max_ms: +t.max.toFixed(2), avg_ms: +t.avg.toFixed(2),
    throughput_rps: +(n / seconds(DURATION)).toFixed(1),
    error_rate: data.metrics[errors] ? +data.metrics[errors].values.rate.toFixed(5) : 0,
  };
}

export function handleSummary(data) {
  const all = stats(data, 'request_latency', 'request_errors', 'request_count');
  const endpoints = {};
  for (const [key, name] of Object.entries(ENDPOINTS)) {
    const s = stats(data, `latency_${key}`, `errors_${key}`, `count_${key}`);
    if (s) endpoints[name] = s;
  }
  const result = { label: LABEL, vus: VUS, think_ms: THINK_MS, duration_s: seconds(DURATION), ...all, endpoints };
  return {
    stdout: `[${LABEL}] vus=${VUS} rps=${result.throughput_rps} p99=${result.p99_ms}ms ` +
      Object.entries(endpoints).map(([name, s]) => `| ${name} p99=${s.p99_ms}ms`).join(' ') + '\n',
    [`/results/k6-${LABEL}.json`]: JSON.stringify(result, null, 2),
  };
}
