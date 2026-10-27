# Headroom

Headroom is a coding agent that has to prove its changes work.

Give it a web service that misses one of its SLOs: latency, throughput or error rate, on one endpoint or several. It
finds out why, writes several candidate fixes, and hands one over only after the service's own tests and repeated load tests show that it works. NVIDIA Nemotron 3 Ultra
(`nvidia/Nemotron-3-Ultra-550b-a55b`, served by Nebius Token Factory) proposes the causes and writes the code. It never
decides whether a fix worked. Measurements and tests decide that, and a person approves the final change.

**Live demo:** https://headroom.haseebulhaq55.workers.dev. Start a run and watch it, or open an earlier one.

Built for the Nebius x NVIDIA Global AI Hackathon 2026, Coding and Agentic Engineering track.

## What a run looks like

From a real run on an earlier, single-endpoint version of the pricing service, which caches each price for 2 seconds
while a sale sends most traffic to five products:

1. **Measure.** With 200 concurrent shoppers, `GET /products/{sku}/price` has a p99 of 1,858 ms. The target is 100 ms.
   All 8 correctness tests pass, so the service works. It is just slow.
2. **Propose causes.** Nemotron reads the endpoint's code and suggests three: a cache stampede (70%), a slow demand
   query (50%), and a connection pool that is too small (30%). Each comes with a prediction that could prove it wrong.
3. **Test them.** Headroom load-tests the unmodified service at 50, 100 and 200 users and reports what it measured.
   In each 20-second window the price calculation ran 307, 523 and 1,592 times. With a 2-second cache, all 24
   products together should need at most about 240. Nemotron confirms the stampede (95%).
4. **Race fixes.** Nemotron writes three different fixes. Each runs in its own copy of the service against the full
   test suite and the same load test. Stale-while-revalidate wins with a p99 of 3 ms and every test passing.
5. **Prove it.** The winner and the original code are each load-tested 7 more times. A fix is accepted only if the 95%
   confidence interval of its median p99 lies entirely under the target. Here it was 2 to 3 ms.
6. **Stop for review.** Headroom shows the diff and waits. `headroom approve` applies it.

A run takes 15 to 25 minutes, almost all of it load testing, and makes 3 to 12 model calls.

## How fixes are judged

- **A failing test rejects a fix,** however fast it is. Caching prices for 5 minutes was the fastest option on the
  pricing service (1.7 ms), and it was rejected because a price change must show within 3 seconds. In one run Nemotron
  proposed a precomputed demand table that reached 2 ms and failed 6 of 8 tests.
- **A fix must beat the original and meet the target** under the same load, as measured by Headroom. The model's own
  claims about its fix are not used.
- **Every goal must hold, and none may get worse.** A service can have goals on several endpoints. A fix must meet all
  of them, and one that makes an endpoint miss a goal it was meeting is rejected even if it fixes the slow one. On the
  pricing service the stampede also slowed `POST /orders` to 2.1 s, and verification checks that the fix brings orders
  back under their own 150 ms goal as well.
- **One good run proves nothing.** Verification repeats the load test 7 times and uses a bootstrap confidence interval,
  so a single lucky or unlucky run cannot decide the outcome.
- **Error rate and memory are limits too.** In one run, "make the connection pool bigger" passed every test but
  caused 5% errors under load, so it was rejected.

## Results

Every run below was a full investigation, from baseline to verified patch, on a standard 4-core GitHub Actions runner.
Each scenario is a small FastAPI and PostgreSQL service with one realistic performance bug that Headroom is not told
about.

| Scenario | Bug | Goal | Before | After | Runs that met every goal |
|---|---|---|---|---|---|
| Pricing | Cache stampede on hot products during a sale | price p99 under 100 ms | 0.1 to 1.9 s | 1 to 26 ms | 5 of 5 |
| Pricing, two goals | The same stampede, now also slowing orders | price p99 under 100 ms, order p99 under 150 ms | prices 1.8 to 2.1 s | prices 7 to 13 ms, orders 34 to 62 ms | 3 of 3 |
| Checkout | A global lock serializes stock reservations | p99 under 100 ms | 763 to 855 ms | 8 to 9 ms | 3 of 3 |
| Checkout, throughput | The same lock caps reservations per second | at least 240 req/s | 187 req/s | 249 req/s | 1 of 1 |
| Catalog | Two extra queries per product on a category page | p99 under 50 ms | 127 ms | 4 to 7 ms | 2 of 2 |
| Dashboard | Five queries run one after another against a database 15 ms away | p99 under 100 ms | 193 to 196 ms | 71 to 73 ms | 2 of 2 |
| Accounts | Password hashing blocks the async event loop | p99 under 50 ms | 2.5 s | 5 ms | 1 of 3 |

On Pricing, Nemotron named the stampede in 4 of 5 runs. In the fifth it blamed the connection pool, but it still wrote
several different fixes, and the race picked request coalescing, which fixed the actual cause. One Pricing baseline
measured only 107 ms, against the usual 1.7 s, because GitHub runners vary in speed. It still missed the target. The
two-goal version adds more traffic so the stampede always develops; Nemotron named it in 2 of 3 runs, and all three
were fixed in the first round. In the throughput run, the fix with the highest throughput failed a concurrency test
and was rejected; per-SKU locking won. On Dashboard, one run merged the five queries into one and the other ran them
concurrently; in the second, the quickest attempt failed every request and was rejected.

When Headroom cannot support a cause with evidence, it stops and says so rather than shipping a guess. Both unresolved
Accounts runs ended that way, before the two reasoning rules in `headroom/agent/prompts.py` were added. Each rule came
from reading a failed run: a measurement that falls between two predictions does not disprove a hypothesis, and
neither does a symptom the hypothesis itself would cause.

Every scenario also has hand-written reference fixes, including deliberately broken ones, which check that its tests
catch bad fixes and that its target is reachable (`headroom eval --reference`).

## Try it

The live demo runs a randomized version of one scenario on GitHub Actions and streams it to the page. It allows one run
at a time and three a day, to keep model and runner costs predictable.

Running it yourself needs Docker with Compose v2, [uv](https://docs.astral.sh/uv/), and a Nebius Token Factory API key.

```bash
uv sync
cp .env.example .env           # set NEBIUS_API_KEY and NEMOTRON_MODEL
uv run headroom investigate evals/scenarios/pricing-service
uv run headroom show latest    # the timeline and the verified diff
uv run headroom approve latest # apply the diff
```

To watch a run in the browser as it happens:

```bash
npm --prefix dashboard ci && npm --prefix dashboard run build
uv run headroom serve          # http://127.0.0.1:8765/headroom/
```

The building blocks also work without a model:

```bash
uv run headroom benchmark examples/checkout-service --concurrency 25,100,500
uv run headroom race examples/checkout-service -c fix-a=a.diff -c fix-b=b.diff
uv run headroom verify examples/checkout-service --patch fix-b=b.diff --runs 10
uv run headroom eval --reference
```

## Using it on your own service

Headroom needs a Docker Compose file that starts the service, a service that runs your tests, a k6 load test, and a
`headroom.yaml` that connects them:

```yaml
service: checkout-service
objectives:                     # the first is the one being investigated
  - endpoint: POST /inventory/reserve
    metric: p99_ms                # or p50_ms, p95_ms, throughput_rps, error_rate
    target: 100
  - endpoint: GET /products
    metric: p99_ms
    target: 50
workload:
  concurrency: 500
  think_ms: 2000
runtime:
  compose_file: docker-compose.yml
  app_service: app
  tests_service: tests
  load_service: k6
  load_script: /load/reserve.js
  metrics_path: /metrics
  protected_paths: [tests/*, load/*, headroom.yaml]
```

A fix may not change `protected_paths`, so it cannot pass by editing the tests or the load test. With goals on several
endpoints, the load test reports each endpoint separately; [the pricing load test](evals/scenarios/pricing-service/load/prices.js)
shows how. The optional
`/metrics` endpoint exposes in-process timing spans; the examples include a 90-line implementation.

## How it is built

- `headroom/agent/`: the investigation loop as an explicit state machine, the prompts, and the Nemotron client. Each
  step is recorded as an event, which is what the dashboard replays or streams.
- `headroom/benchmark/`: the benchmark runner, the rule-based judge, and the verification statistics.
- `headroom/execution/`: runs each fix in its own copy of the repository and its own Docker Compose project.
- `headroom/telemetry/`: container resources and PostgreSQL activity, sampled during load.
- `dashboard/`: the React front end, plus a Cloudflare Worker that starts public runs on GitHub Actions and relays
  their events to the browser. See [docs/cloudflare.md](docs/cloudflare.md).
- `evals/`: the scenarios, their ground truth, and reference fixes. The ground truth lives outside each service's
  repository, so the model never sees it.

## Limitations

- Goals are per-endpoint latency, throughput or error rate. It does not yet target memory, CPU or cost, and it
  investigates one goal at a time, using the others as limits a fix must respect.
- It reproduces the problem with a synthetic load test in a copy of the service. It does not read production traffic
  or traces.
- The scenarios are small services with one bug each. They are realistic, but they were written for this project.
- Results vary between runs because the model's reasoning varies. The judge and the verification step are what stop
  a wrong diagnosis from becoming a bad change.

## License

MIT. See [LICENSE](LICENSE).
