# HotPath

**An autonomous performance engineer that investigates SLO violations, runs controlled
experiments, and ships only verified fixes.**

> HotPath doesn't ask AI whether its optimization worked. It makes the system prove it.

Built for the Nebius x NVIDIA Global AI Hackathon 2026 (Coding and Agentic Engineering track).

Status: early development. See [PROGRESS.md](PROGRESS.md).

## Quick start

Requires Docker (Compose v2) and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
# Start the service, run its tests, load-test it, collect metrics, tear down, print JSON
uv run hotpath benchmark examples/checkout-service
uv run hotpath benchmark examples/checkout-service --concurrency 25,100,500 -o result.json
```

Each run happens in its own Docker Compose project (unique name and ports), and its
artifacts (JUnit XML, k6 summaries, server spans, `result.json`) land in `.hotpath/runs/<run>/`.

A target repository describes its objective and how to run it in a `hotpath.yaml`
(see [examples/checkout-service/hotpath.yaml](examples/checkout-service/hotpath.yaml)).

## Repository

| Path | What |
|---|---|
| `hotpath/` | The HotPath package: config, benchmark runner, Docker execution, telemetry, CLI |
| `tests/` | Unit tests for HotPath itself |
| `examples/checkout-service/` | Demo target: FastAPI + Postgres service with a real lock-contention SLO violation |
| `docs/` | Notes, including hackathon feedback |
| `PROGRESS.md` | Living progress log and submission checklist |
