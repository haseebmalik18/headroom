"""Per-repository Headroom configuration (`headroom.yaml`)."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

CONFIG_FILE = "headroom.yaml"


Metric = Literal["p50_ms", "p95_ms", "p99_ms", "throughput_rps", "error_rate"]

# What each objective metric means, and which direction is better.
METRICS: dict[str, tuple[str, bool]] = {   # metric -> (description, higher is better)
    "p50_ms": ("p50 latency", False),
    "p95_ms": ("p95 latency", False),
    "p99_ms": ("p99 latency", False),
    "throughput_rps": ("throughput", True),
    "error_rate": ("error rate", False),
}


class Objective(BaseModel):
    """One measurable SLO on one endpoint: latency, throughput or error rate."""

    endpoint: str
    metric: Metric = "p99_ms"
    target: float

    @property
    def higher_is_better(self) -> bool:
        return METRICS[self.metric][1]

    def met(self, value: float) -> bool:
        return value >= self.target if self.higher_is_better else value < self.target

    def better(self, a: float, b: float) -> bool:
        """Whether `a` is strictly better than `b` for this objective."""
        return a > b if self.higher_is_better else a < b

    def show(self, value: float) -> str:
        if self.metric == "error_rate":
            return f"{value * 100:.3f}".rstrip("0").rstrip(".") + "%"
        unit = "req/s" if self.metric == "throughput_rps" else "ms"
        return f"{value:,.0f} {unit}" if value >= 100 or self.higher_is_better else f"{value:.1f} {unit}"

    def text(self) -> str:
        name = METRICS[self.metric][0]
        if self.metric == "error_rate":
            return f"{name} under {self.target * 100:g}%"
        return f"{name} of at least {self.show(self.target)}" if self.higher_is_better else f"{name} under {self.target:g} ms"


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
    # Every SLO the service must meet. The first is the primary one the investigation is about;
    # a fix must meet all of them and may not break one the original code was meeting.
    objectives: list[Objective] = Field(min_length=1)
    constraints: Constraints = Constraints()
    workload: Workload
    runtime: Runtime

    @model_validator(mode="before")
    @classmethod
    def _one_or_many(cls, data):
        if isinstance(data, dict) and "objective" in data and "objectives" not in data:
            data = {**data, "objectives": [data["objective"]]}
            del data["objective"]
        return data

    @property
    def objective(self) -> Objective:
        return self.objectives[0]


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
