"""Per-repository Headroom configuration (`headroom.yaml`)."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

CONFIG_FILE = "headroom.yaml"


class Objective(BaseModel):
    endpoint: str
    metric: Literal["p50_ms", "p95_ms", "p99_ms"] = "p99_ms"
    target: float


class Constraints(BaseModel):
    tests: Literal["pass"] = "pass"
    max_error_rate: float = 0.001
    max_memory_mb: float | None = None


class Workload(BaseModel):
    concurrency: int
    think_ms: float = 2000
    warmup: str = "10s"
    duration: str = "30s"


class Runtime(BaseModel):
    compose_file: str = "docker-compose.yml"
    app_service: str = "app"
    app_port: int = 8000
    db_service: str | None = "db"
    tests_service: str = "tests"
    load_service: str = "k6"
    load_script: str
    metrics_path: str | None = "/metrics"
    # Files a candidate patch may never modify: the judges of correctness and speed.
    protected_paths: list[str] = ["tests/*", "load/*", "headroom.yaml", "docker-compose.yml", "Dockerfile"]


class ProjectConfig(BaseModel):
    service: str
    objective: Objective
    constraints: Constraints = Constraints()
    workload: Workload
    runtime: Runtime


def load_config(repo: Path) -> ProjectConfig:
    path = Path(repo) / CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(f"{path} not found: every target repository needs a {CONFIG_FILE}")
    return ProjectConfig.model_validate(yaml.safe_load(path.read_text()))


_DURATION = re.compile(r"^(\d+(?:\.\d+)?)(ms|s|m)$")


def parse_duration(text: str) -> float:
    """'10s' / '500ms' / '2m' -> seconds."""
    match = _DURATION.match(text.strip())
    if not match:
        raise ValueError(f"invalid duration {text!r}; use e.g. 500ms, 10s, 2m")
    value, unit = float(match[1]), match[2]
    return {"ms": value / 1000, "s": value, "m": value * 60}[unit]
