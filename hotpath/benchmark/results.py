"""Structured benchmark results.

Everything here is produced by deterministic parsing of tool output
(pytest JUnit XML, k6 summaries, docker stats, the service's /metrics);
no model is involved in turning measurements into numbers.
"""

import statistics
import xml.etree.ElementTree as ET
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from hotpath.config import Objective


class TestFailure(BaseModel):
    __test__ = False  # not a pytest test class

    name: str
    message: str


class TestReport(BaseModel):
    __test__ = False  # not a pytest test class

    total: int
    passed: int
    failed: int
    errors: int
    skipped: int
    duration_s: float
    failures: list[TestFailure]

    @property
    def ok(self) -> bool:
        return self.total > 0 and self.failed == 0 and self.errors == 0


class LoadReport(BaseModel):
    """Client-side view of one load run (from the k6 summary JSON)."""

    model_config = ConfigDict(populate_by_name=True)

    label: str
    concurrency: int = Field(alias="vus")
    think_ms: float
    duration_s: float
    requests: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    avg_ms: float
    throughput_rps: float
    error_rate: float


class SpanStats(BaseModel):
    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


class ContainerUsage(BaseModel):
    cpu_percent_avg: float
    cpu_percent_max: float
    memory_mb_max: float
    samples: int


class LoadRun(BaseModel):
    load: LoadReport
    spans: dict[str, SpanStats] = {}
    containers: dict[str, ContainerUsage] = {}


class BenchmarkResult(BaseModel):
    service: str
    label: str
    repo: str
    started_at: datetime
    finished_at: datetime
    objective: Objective
    tests: TestReport | None = None
    runs: list[LoadRun] = []
    error: str | None = None

    @property
    def primary(self) -> LoadRun | None:
        """The first run at the highest concurrency, which is what the SLO is judged on."""
        return max(self.runs, key=lambda r: r.load.concurrency, default=None)

    @property
    def primary_runs(self) -> list[LoadRun]:
        """Every (repeated) run at the highest concurrency."""
        if not self.runs:
            return []
        top = max(r.load.concurrency for r in self.runs)
        return [r for r in self.runs if r.load.concurrency == top]

    def median_load(self, field: str) -> float | None:
        """Median of a LoadReport field across the primary runs (robust to one noisy run)."""
        values = [getattr(r.load, field) for r in self.primary_runs]
        return statistics.median(values) if values else None

    @property
    def slo_met(self) -> bool | None:
        value = self.median_load(self.objective.metric)
        return None if value is None else value < self.objective.target

    def summary(self) -> dict:
        """Flat headline numbers for the primary run."""
        out: dict = {"label": self.label, "error": self.error, "slo_met": self.slo_met}
        if self.tests:
            out |= {"tests_passed": self.tests.passed, "tests_total": self.tests.total, "tests_ok": self.tests.ok}
        run = self.primary
        if run:
            load = run.load
            out |= {
                "concurrency": load.concurrency,
                "p50_ms": load.p50_ms,
                "p95_ms": load.p95_ms,
                "p99_ms": load.p99_ms,
                "throughput_rps": load.throughput_rps,
                "error_rate": load.error_rate,
            }
            app = run.containers.get("app")
            if app:
                out |= {"memory_mb": app.memory_mb_max, "cpu_percent": app.cpu_percent_avg}
            out["span_p99_ms"] = {name: s.p99_ms for name, s in run.spans.items()}
        return out


def parse_junit(xml_text: str) -> TestReport:
    root = ET.fromstring(xml_text)
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")

    total = failed = errors = skipped = 0
    duration = 0.0
    failures: list[TestFailure] = []
    for suite in suites:
        total += int(suite.get("tests", 0))
        failed += int(suite.get("failures", 0))
        errors += int(suite.get("errors", 0))
        skipped += int(suite.get("skipped", 0))
        duration += float(suite.get("time", 0))
        for case in suite.iter("testcase"):
            problem = case.find("failure")
            if problem is None:
                problem = case.find("error")
            if problem is not None:
                message = (problem.get("message") or "").strip().splitlines()
                failures.append(
                    TestFailure(
                        name=f"{case.get('classname')}::{case.get('name')}",
                        message=message[0] if message else "",
                    )
                )

    return TestReport(
        total=total,
        passed=total - failed - errors - skipped,
        failed=failed,
        errors=errors,
        skipped=skipped,
        duration_s=duration,
        failures=failures,
    )
