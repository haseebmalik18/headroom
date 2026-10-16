"""PostgreSQL activity sampling during load.

Answers "is the database the bottleneck?" from the database's own point of view:
how many client connections are actually executing, what they are waiting on,
and how fast transactions commit.
"""

import asyncio
import time
from collections import Counter

from pydantic import BaseModel

from hotpath.benchmark.results import DbActivity
from hotpath.execution.docker import ComposeProject

QUERY = """
select 'active|' || count(*) from pg_stat_activity
  where backend_type = 'client backend' and state = 'active' and pid <> pg_backend_pid();
select 'idle_in_transaction|' || count(*) from pg_stat_activity
  where backend_type = 'client backend' and state like 'idle in transaction%';
select 'connections|' || count(*) from pg_stat_activity
  where backend_type = 'client backend' and pid <> pg_backend_pid();
select 'commits|' || xact_commit from pg_stat_database where datname = current_database();
select 'wait|' || kind || '|' || event || '|' || n from (
  select coalesce(wait_event_type, 'CPU') as kind, coalesce(wait_event, 'running') as event, count(*) as n
  from pg_stat_activity
  where backend_type = 'client backend' and state = 'active' and pid <> pg_backend_pid()
  group by 1, 2) as waits;
"""


class ActivitySample(BaseModel):
    at: float
    active: int
    idle_in_transaction: int
    connections: int
    commits: int
    waits: dict[str, int]


def parse_activity_output(output: str, at: float) -> ActivitySample:
    values: dict[str, int] = {}
    waits: dict[str, int] = {}
    for line in output.strip().splitlines():
        parts = line.strip().split("|")
        if parts[0] == "wait" and len(parts) == 4:
            if int(parts[3]):
                waits[f"{parts[1]}:{parts[2]}"] = int(parts[3])
        elif len(parts) == 2 and parts[1].isdigit():
            values[parts[0]] = int(parts[1])
    missing = {"active", "idle_in_transaction", "connections", "commits"} - values.keys()
    if missing:
        raise ValueError(f"unexpected pg_stat_activity output (missing {sorted(missing)}): {output[:200]}")
    return ActivitySample(at=at, waits=waits, **values)


def summarize_activity(samples: list[ActivitySample]) -> DbActivity:
    n = len(samples)
    waits: Counter[str] = Counter()
    for s in samples:
        waits.update(s.waits)
    elapsed = samples[-1].at - samples[0].at
    return DbActivity(
        samples=n,
        active_connections_avg=round(sum(s.active for s in samples) / n, 2),
        active_connections_max=max(s.active for s in samples),
        idle_in_transaction_avg=round(sum(s.idle_in_transaction for s in samples) / n, 2),
        pool_connections_max=max(s.connections for s in samples),
        commits_per_s=round((samples[-1].commits - samples[0].commits) / elapsed, 1) if elapsed > 0 else None,
        wait_events=dict(waits.most_common()),
    )


class PostgresActivitySampler:
    def __init__(self, project: ComposeProject, db_service: str, interval_s: float = 1.0):
        self.project = project
        self.db_service = db_service
        self.interval_s = interval_s
        self._samples: list[ActivitySample] = []
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._samples = []
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> DbActivity | None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        return summarize_activity(self._samples) if self._samples else None

    async def _loop(self) -> None:
        command = f'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -c "{QUERY}"'
        while True:
            result = await self.project.compose("exec", "-T", self.db_service, "sh", "-c", command,
                                                timeout=30, check=False)
            if result.returncode == 0:
                try:
                    self._samples.append(parse_activity_output(result.output, at=time.monotonic()))
                except ValueError:
                    pass
            await asyncio.sleep(self.interval_s)
