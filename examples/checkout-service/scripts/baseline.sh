#!/usr/bin/env bash
# Reproduce the checkout-service baseline from a clean slate:
#   fresh database -> tests -> load sweep (one k6 run per concurrency level) -> teardown.
#
# Env overrides:
#   LEVELS="25 100 500"   concurrent shoppers per run
#   THINK_MS=2000         mean pause between a shopper's requests
#   WARMUP=10s DURATION=30s
#   KEEP=1                leave the stack running afterwards
set -euo pipefail
cd "$(dirname "$0")/.."

LEVELS="${LEVELS:-25 100 500}"
THINK_MS="${THINK_MS:-2000}"
WARMUP="${WARMUP:-10s}"
DURATION="${DURATION:-30s}"
APP="http://localhost:${APP_PORT:-8000}"

mkdir -p results
echo "==> Starting fresh environment"
docker compose down -v --remove-orphans >/dev/null 2>&1 || true
docker compose up -d --build --wait db app

echo "==> Running tests"
docker compose --profile tools run --rm --build tests

for vus in $LEVELS; do
  echo "==> Load: ${vus} concurrent shoppers, think ${THINK_MS}ms, ${DURATION} measured after ${WARMUP} warmup"
  # Server-side spans should cover the measured window only: reset when warmup ends.
  (sleep "${WARMUP%s}"; curl -fsS -X POST "$APP/metrics/reset") &
  docker compose --profile tools run --rm \
    -e VUS="$vus" -e THINK_MS="$THINK_MS" -e WARMUP="$WARMUP" -e DURATION="$DURATION" -e LABEL="vus-$vus" \
    k6 run --no-color /load/reserve.js 2>/dev/null | grep '^\[' || true
  wait
  curl -fsS "$APP/metrics" > "results/server-vus-$vus.json"
  python3 scripts/summarize_metrics.py < "results/server-vus-$vus.json"
done

if [[ "${KEEP:-0}" != "1" ]]; then
  echo "==> Tearing down"
  docker compose down -v >/dev/null
fi
echo "==> Results written to results/"
