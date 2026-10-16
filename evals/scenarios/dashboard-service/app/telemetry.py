"""Lightweight in-process span timing, exported as JSON at GET /metrics.

Spans are named timings (milliseconds) kept in bounded in-memory buffers.
This is deliberately small: enough to see where request time goes without
running a tracing backend.
"""

import os
import time
from array import array
from collections import defaultdict
from contextlib import contextmanager

import psutil

_MAX_SAMPLES = 200_000


class _Samples:
    """Fixed-size ring buffer of floats.

    Backed by array('d') rather than a list/deque so the garbage collector never
    has to walk hundreds of thousands of float objects (which stalls the event loop).
    """

    __slots__ = ("values", "next", "size")

    def __init__(self):
        self.values = array("d", bytes(8 * _MAX_SAMPLES))
        self.next = 0
        self.size = 0

    def append(self, value: float) -> None:
        self.values[self.next] = value
        self.next = (self.next + 1) % _MAX_SAMPLES
        self.size = min(self.size + 1, _MAX_SAMPLES)

    def sorted(self) -> list[float]:
        return sorted(self.values[: self.size])


_samples: dict[str, _Samples] = defaultdict(_Samples)
_process = psutil.Process(os.getpid())
_window_started = time.monotonic()


def record(name: str, ms: float) -> None:
    _samples[name].append(ms)


@contextmanager
def span(name: str):
    start = time.perf_counter()
    try:
        yield
    finally:
        record(name, (time.perf_counter() - start) * 1000)


def _percentile(sorted_values: list[float], q: float) -> float:
    # Nearest-rank percentile.
    index = max(0, min(len(sorted_values) - 1, round(q * len(sorted_values) + 0.5) - 1))
    return sorted_values[index]


def snapshot() -> dict:
    spans = {}
    for name, values in list(_samples.items()):
        data = values.sorted()
        if not data:
            continue
        spans[name] = {
            "count": len(data),
            "mean_ms": round(sum(data) / len(data), 3),
            "p50_ms": round(_percentile(data, 0.50), 3),
            "p95_ms": round(_percentile(data, 0.95), 3),
            "p99_ms": round(_percentile(data, 0.99), 3),
            "max_ms": round(data[-1], 3),
        }
    return {
        "window_seconds": round(time.monotonic() - _window_started, 3),
        "process": {
            "rss_mb": round(_process.memory_info().rss / 1024 / 1024, 1),
            "cpu_percent": _process.cpu_percent(interval=None),
        },
        "spans": spans,
    }


def reset() -> None:
    global _window_started
    _samples.clear()
    _process.cpu_percent(interval=None)  # restart the CPU measurement window
    _window_started = time.monotonic()


class RequestTimingMiddleware:
    """Records one span per HTTP request, keyed by method and route template."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"].startswith("/metrics"):
            await self.app(scope, receive, send)
            return
        start = time.perf_counter()
        try:
            await self.app(scope, receive, send)
        finally:
            route = scope.get("route")
            path = getattr(route, "path", scope["path"])
            record(f"http {scope['method']} {path}", (time.perf_counter() - start) * 1000)
