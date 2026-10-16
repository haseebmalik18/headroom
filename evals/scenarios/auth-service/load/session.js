// Load test: signed-in users reading their profile while others log in.
//
// readers: VUS signed-in users call GET /me, pausing ~THINK_MS between calls
//          (this is the endpoint being measured).
// logins:  LOGIN_RATE password logins per second from other users.
// Only GET /me requests sent after WARMUP, during DURATION, are reported.
//
// Env: BASE_URL, VUS, WARMUP, DURATION, THINK_MS, LOGIN_RATE, LABEL

import http from 'k6/http';
import exec from 'k6/execution';
import { sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const VUS = parseInt(__ENV.VUS || '200', 10);
const WARMUP = __ENV.WARMUP || '10s';
const DURATION = __ENV.DURATION || '30s';
const THINK_MS = parseFloat(__ENV.THINK_MS || '500');
const LOGIN_RATE = parseInt(__ENV.LOGIN_RATE || '8', 10);
const LABEL = __ENV.LABEL || `vus-${VUS}`;

function seconds(duration) {
  const m = /^(\d+(?:\.\d+)?)(ms|s|m)$/.exec(duration);
  const value = parseFloat(m[1]);
  return m[2] === 'ms' ? value / 1000 : m[2] === 'm' ? value * 60 : value;
}

const WARMUP_MS = seconds(WARMUP) * 1000;
const MEASURE_END_MS = WARMUP_MS + seconds(DURATION) * 1000;
const TOTAL = `${MEASURE_END_MS / 1000}s`;

const latency = new Trend('me_latency', true);
const errors = new Rate('me_errors');
const requests = new Counter('me_count');
const loginLatency = new Trend('login_latency', true);

export const options = {
  discardResponseBodies: false,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  scenarios: {
    readers: { executor: 'constant-vus', vus: VUS, duration: TOTAL, gracefulStop: '10s', exec: 'reader' },
    logins: {
      executor: 'constant-arrival-rate', rate: LOGIN_RATE, timeUnit: '1s', duration: TOTAL,
      preAllocatedVUs: 20, maxVUs: 200, exec: 'login',
    },
  },
};

const json = { headers: { 'Content-Type': 'application/json' } };

function user(n) {
  const name = `user${String(1 + (n % 100)).padStart(3, '0')}`;
  return { username: name, password: `pass-${name}` };
}

let token = null;

export function reader() {
  if (token === null) {
    sleep((THINK_MS / 1000) * Math.random());
    const res = http.post(`${BASE_URL}/login`, JSON.stringify(user(exec.vu.idInTest)), json);
    token = res.status === 200 ? res.json('token') : null;
    return;
  }
  const sentAt = exec.instance.currentTestRunDuration;
  const res = http.get(`${BASE_URL}/me`, { headers: { Authorization: `Bearer ${token}` }, tags: { name: 'me' } });
  if (sentAt >= WARMUP_MS && sentAt < MEASURE_END_MS) {
    latency.add(res.timings.duration);
    errors.add(res.status !== 200);
    requests.add(1);
  }
  sleep((THINK_MS / 1000) * (0.5 + Math.random()));
}

export function login() {
  const res = http.post(`${BASE_URL}/login`, JSON.stringify(user(Math.floor(Math.random() * 100))), json);
  if (exec.instance.currentTestRunDuration >= WARMUP_MS) {
    loginLatency.add(res.timings.duration);
  }
}

export function handleSummary(data) {
  const t = data.metrics.me_latency.values;
  const l = data.metrics.login_latency ? data.metrics.login_latency.values : null;
  const count = data.metrics.me_count ? data.metrics.me_count.values.count : 0;
  const result = {
    label: LABEL, vus: VUS, think_ms: THINK_MS, duration_s: seconds(DURATION), requests: count,
    p50_ms: +t.med.toFixed(2), p95_ms: +t['p(95)'].toFixed(2), p99_ms: +t['p(99)'].toFixed(2),
    max_ms: +t.max.toFixed(2), avg_ms: +t.avg.toFixed(2),
    throughput_rps: +(count / seconds(DURATION)).toFixed(1),
    error_rate: +data.metrics.me_errors.values.rate.toFixed(5),
    login_rate: LOGIN_RATE,
    login_p99_ms: l ? +l['p(99)'].toFixed(2) : null,
  };
  return {
    stdout: `[${LABEL}] vus=${VUS} me p50=${result.p50_ms}ms p99=${result.p99_ms}ms; login p99=${result.login_p99_ms}ms\n`,
    [`/results/k6-${LABEL}.json`]: JSON.stringify(result, null, 2),
  };
}
