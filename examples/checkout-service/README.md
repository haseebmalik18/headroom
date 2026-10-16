# checkout-service

Checkout backend for the storefront: catalog, inventory reservations, and orders.
FastAPI + asyncpg + PostgreSQL.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Readiness (checks the DB) |
| `GET /products` | Catalog listing (1,000 seeded SKUs) |
| `POST /inventory/reserve` | Hold stock for a SKU: `{"sku": "SKU-00042", "quantity": 1}` |
| `POST /checkout` | Turn a held reservation into an order: `{"reservation_id": 123}` |
| `GET /metrics`, `POST /metrics/reset` | In-process span timings (JSON) |

**SLO:** `POST /inventory/reserve` p99 < 100 ms.

## Run it

Requires Docker (with Compose v2). Nothing else needs to be installed on the host.

```bash
# Full baseline: fresh DB, tests, load at 25 / 100 / 500 shoppers, teardown (~3 min)
./scripts/baseline.sh

# Or step by step
docker compose up -d --build --wait db app
docker compose --profile tools run --rm --build tests                 # pytest
docker compose --profile tools run --rm -e VUS=500 k6 run /load/reserve.js
curl -s localhost:8000/metrics | python3 scripts/summarize_metrics.py
docker compose down -v
```

`baseline.sh` options: `LEVELS="25 100 500"`, `THINK_MS=2000`, `WARMUP=10s`, `DURATION=30s`, `KEEP=1`.

## Workload model

`load/reserve.js` simulates `VUS` concurrent shoppers. Each reserves a random SKU,
then pauses ~`THINK_MS` (uniform 0.5×–1.5×) before the next request. Start times
are staggered, and only requests sent during the measured window (after warmup)
are reported. Results are written to `results/k6-<label>.json`.

## Test suite

`tests/` are black-box tests against the running service (17 tests):

- `test_api.py`: endpoint behaviour, validation, checkout flow, audit events.
- `test_inventory_concurrency.py`: fires dozens of simultaneous reservations
  and asserts inventory is conserved: never oversold, `stock + reserved ==
  initial`, each success sees a distinct remaining stock level.

## Environment notes

- **DB network hop.** The database container adds `DB_NETWORK_DELAY` (default
  `500us`) of egress latency with `tc netem`. Docker's in-VM bridge is ~0.06 ms
  RTT, far faster than a real app→database hop. On Docker Desktop for Mac,
  netem's effective granularity gives ~1–2 ms per query. Set
  `DB_NETWORK_DELAY=0` to disable it.
- The service runs a single uvicorn worker.
