# HotPath

**An autonomous performance engineer that investigates SLO violations, runs controlled
experiments, and ships only verified fixes.**

> HotPath doesn't ask AI whether its optimization worked. It makes the system prove it.

Built for the Nebius x NVIDIA Global AI Hackathon 2026 (Coding and Agentic Engineering track).

Status: early development.

## Quick start

Requires Docker (Compose v2) and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env        # add NEBIUS_API_KEY, then pick a model:
uv run hotpath models       # Nemotron models available on your Token Factory account

# The full autonomous investigation, ending at a verified patch awaiting approval
uv run hotpath investigate examples/checkout-service
uv run hotpath show latest      # replay the timeline and see the diff
uv run hotpath approve latest   # human approval: apply the verified diff

# Building blocks (no model needed)
uv run hotpath benchmark examples/checkout-service --concurrency 25,100,500
uv run hotpath experiment examples/checkout-service --concurrency 100,500 --measure db_activity,app_spans
uv run hotpath race examples/checkout-service -c fix-a=a.diff -c fix-b=b.diff
uv run hotpath verify examples/checkout-service --patch fix-b=b.diff --runs 10
```

Each run happens in its own Docker Compose project (unique name and ports), and its
artifacts (JUnit XML, k6 summaries, server spans, `result.json`) land in `.hotpath/runs/<run>/`.

A target repository describes its objective and how to run it in a `hotpath.yaml`
(see [examples/checkout-service/hotpath.yaml](examples/checkout-service/hotpath.yaml)).

## Live demo

Build the dashboard once, then start the live server from the project root:

```bash
npm --prefix dashboard ci
npm --prefix dashboard run build
uv run hotpath serve
```

Open **http://127.0.0.1:8765/hotpath/**. In a second terminal, start an investigation:

```bash
uv run hotpath investigate examples/checkout-service
```

Docker must be running, and `NEBIUS_API_KEY` and `NEMOTRON_MODEL` must be configured
as in Quick start. The investigation uses model credits; the dashboard itself only
reads events. It follows measurements, reasoning, candidate tests, and verification
as they happen, then exposes the verified patch for review. It reconnects after a
connection interruption and detects the next investigation automatically. If the
latest run has already ended, it is labeled as completed. History shows saved results
without simulated playback.

For frontend development, run `npm --prefix dashboard run dev` alongside
`uv run hotpath serve`; Vite proxies `/api` to port 8765.

The public dashboard uses Cloudflare as a small coordinator and a GitHub-hosted
runner for the Docker work. A visitor can start one of the randomized benchmark
cases directly in the browser and watch the same evidence arrive over a live
connection. The runner accepts only a generated run ID and numeric seed; the
repository, model, workload, and commands are fixed by the workflow.

## Repository

Cloudflare hosting configuration and free-plan limits are documented in
[docs/cloudflare.md](docs/cloudflare.md). The hosting build remains separate from
the local dashboard and server.

| Path | What |
|---|---|
| `hotpath/` | The HotPath package: config, benchmark runner, Docker execution, telemetry, CLI |
| `tests/` | Unit tests for HotPath itself |
| `examples/checkout-service/` | Demo target: FastAPI + Postgres service with a real lock-contention SLO violation |
