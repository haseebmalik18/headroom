import json

import pytest

from hotpath.benchmark.results import LoadReport, parse_junit
from hotpath.telemetry.collector import parse_docker_stats_line, parse_memory_mb, parse_percent

JUNIT_PASS = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" time="0.91">
<testcase classname="tests.test_api" name="test_health" time="0.01"/>
<testcase classname="tests.test_api" name="test_products" time="0.02"/>
</testsuite></testsuites>"""

JUNIT_FAIL = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" errors="1" failures="1" skipped="1" tests="4" time="2.40">
<testcase classname="tests.test_api" name="test_health" time="0.01"/>
<testcase classname="tests.test_inventory_concurrency" name="test_concurrent_reservations_never_oversell[0]" time="0.3">
<failure message="AssertionError: expected exactly 10 successful reservations, got 37&#10;assert 37 == 10">long traceback</failure>
</testcase>
<testcase classname="tests.test_api" name="test_broken_fixture" time="0.0"><error message="fixture 'nope' not found">tb</error></testcase>
<testcase classname="tests.test_api" name="test_skipped" time="0.0"><skipped message="later"/></testcase>
</testsuite></testsuites>"""


def test_parse_junit_all_passing():
    report = parse_junit(JUNIT_PASS)

    assert (report.total, report.passed, report.failed, report.errors, report.skipped) == (2, 2, 0, 0, 0)
    assert report.ok
    assert report.failures == []


def test_parse_junit_failures_and_errors():
    report = parse_junit(JUNIT_FAIL)

    assert (report.total, report.passed, report.failed, report.errors, report.skipped) == (4, 1, 1, 1, 1)
    assert not report.ok
    assert [f.name for f in report.failures] == [
        "tests.test_inventory_concurrency::test_concurrent_reservations_never_oversell[0]",
        "tests.test_api::test_broken_fixture",
    ]
    # Only the first line of the message is kept.
    assert report.failures[0].message == "AssertionError: expected exactly 10 successful reservations, got 37"


def test_load_report_from_k6_summary():
    summary = {
        "label": "load-500",
        "vus": 500,
        "think_ms": 2000,
        "duration_s": 30,
        "requests": 2660,
        "p50_ms": 3644.21,
        "p95_ms": 3805.83,
        "p99_ms": 3848.81,
        "max_ms": 3900.0,
        "avg_ms": 3600.5,
        "throughput_rps": 88.7,
        "error_rate": 0.0,
    }

    report = LoadReport.model_validate_json(json.dumps(summary))

    assert report.concurrency == 500
    assert report.p99_ms == 3848.81
    assert report.throughput_rps == 88.7


@pytest.mark.parametrize("text, value", [("33.72%", 33.72), ("0.00%", 0.0), ("--", 0.0)])
def test_parse_percent(text, value):
    assert parse_percent(text) == value


@pytest.mark.parametrize(
    "text, mb",
    [
        ("65.8MiB / 5.541GiB", 65.8),
        ("1.5GiB / 8GiB", 1536.0),
        ("512KiB / 1GiB", 0.5),
        ("100MB / 1GB", 100 * 1000 * 1000 / 1024 / 1024),
        ("0B / 0B", 0.0),
    ],
)
def test_parse_memory_mb(text, mb):
    assert parse_memory_mb(text) == pytest.approx(mb, rel=1e-3)


def test_parse_docker_stats_line():
    line = json.dumps({"Name": "hotpath-x-app-1", "ID": "abc", "CPUPerc": "37.44%", "MemUsage": "65.82MiB / 5.541GiB"})

    sample = parse_docker_stats_line(line)

    assert sample.name == "hotpath-x-app-1"
    assert sample.cpu_percent == 37.44
    assert sample.memory_mb == pytest.approx(65.82)
