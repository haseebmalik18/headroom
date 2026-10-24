"""Container resource sampling via `docker stats`."""

import asyncio
import json
import re
from dataclasses import dataclass, field

from headroom.benchmark.results import ContainerUsage

_MEM = re.compile(r"^\s*([\d.]+)\s*([KMGT]?i?B)\s*$")
_UNIT_BYTES = {
    "B": 1,
    "KB": 1000, "MB": 1000**2, "GB": 1000**3, "TB": 1000**4,
    "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4,
}


@dataclass
class StatsSample:
    name: str
    cpu_percent: float
    memory_mb: float


def parse_percent(text: str) -> float:
    text = text.strip().rstrip("%")
    try:
        return float(text)
    except ValueError:
        return 0.0


def parse_memory_mb(text: str) -> float:
    """'65.8MiB / 5.541GiB' -> 65.8 (used memory, in MiB)."""
    used = text.split("/")[0]
    match = _MEM.match(used)
    if not match:
        return 0.0
    return float(match[1]) * _UNIT_BYTES[match[2]] / 1024**2


def parse_docker_stats_line(line: str) -> StatsSample:
    data = json.loads(line)
    return StatsSample(
        name=data["Name"],
        cpu_percent=parse_percent(data["CPUPerc"]),
        memory_mb=parse_memory_mb(data["MemUsage"]),
    )


@dataclass
class ContainerStatsSampler:
    """Polls `docker stats` for the given containers until stopped.

    `containers` maps a logical service name (e.g. "app") to a container id.
    """

    containers: dict[str, str]
    interval_s: float = 1.0
    _samples: dict[str, list[StatsSample]] = field(default_factory=dict)
    _task: asyncio.Task | None = None

    def start(self) -> None:
        self._samples = {service: [] for service in self.containers}
        if not self.containers:
            return
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> dict[str, ContainerUsage]:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return {
            service: ContainerUsage(
                cpu_percent_avg=round(sum(s.cpu_percent for s in samples) / len(samples), 2),
                cpu_percent_max=round(max(s.cpu_percent for s in samples), 2),
                memory_mb_max=round(max(s.memory_mb for s in samples), 1),
                samples=len(samples),
            )
            for service, samples in self._samples.items()
            if samples
        }

    async def _loop(self) -> None:
        by_id = {cid: service for service, cid in self.containers.items()}
        while True:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stats", "--no-stream", "--no-trunc", "--format", "{{json .}}", *by_id,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await proc.communicate()
            for line in stdout.decode().splitlines():
                data = json.loads(line)
                service = by_id.get(data.get("ID", ""))
                if service:
                    self._samples[service].append(parse_docker_stats_line(line))
            await asyncio.sleep(self.interval_s)
