"""Isolated Docker Compose environments.

Each ComposeProject gets its own compose project name and host ports, so several
copies of the same service (baseline, candidate A, B, C) can run side by side.
"""

import asyncio
import os
import re
import socket
import uuid
from dataclasses import dataclass
from pathlib import Path


class CommandError(RuntimeError):
    def __init__(self, args: list[str], returncode: int | None, output: str):
        self.returncode = returncode
        self.output = output
        status = "timed out" if returncode is None else f"exited {returncode}"
        tail = "\n".join(output.strip().splitlines()[-15:])
        super().__init__(f"`{' '.join(args)}` {status}\n{tail}")


@dataclass
class CommandResult:
    returncode: int
    output: str  # stdout and stderr, interleaved


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def project_name(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:30] or "run"
    return f"hotpath-{slug}-{uuid.uuid4().hex[:6]}"


class ComposeProject:
    def __init__(self, repo: Path, compose_file: str, name: str, results_dir: Path):
        self.repo = Path(repo).resolve()
        self.compose_file = compose_file
        self.name = name
        self.results_dir = results_dir
        self.app_port = free_port()
        self.db_port = free_port()

    @property
    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "COMPOSE_PROJECT_NAME": self.name,
            "APP_PORT": str(self.app_port),
            "DB_PORT": str(self.db_port),
            "RESULTS_DIR": str(self.results_dir),
        }

    async def compose(self, *args: str, timeout: float = 300, check: bool = True) -> CommandResult:
        cmd = ["docker", "compose", "-f", self.compose_file, "--profile", "tools", *args]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self.repo,
            env=self.env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except TimeoutError:
            proc.kill()
            stdout, _ = await proc.communicate()
            raise CommandError(cmd, None, stdout.decode(errors="replace"))
        result = CommandResult(proc.returncode, stdout.decode(errors="replace"))
        if check and result.returncode != 0:
            raise CommandError(cmd, result.returncode, result.output)
        return result

    async def up(self, *services: str, timeout: float = 600) -> None:
        await self.compose("up", "-d", "--build", "--wait", *services, timeout=timeout)

    async def run(self, service: str, *command: str, env: dict[str, str] | None = None,
                  timeout: float = 600, check: bool = True) -> CommandResult:
        flags = [arg for key, value in (env or {}).items() for arg in ("-e", f"{key}={value}")]
        return await self.compose("run", "--rm", "--build", *flags, service, *command,
                                  timeout=timeout, check=check)

    async def logs(self, service: str, tail: int = 40) -> str:
        result = await self.compose("logs", "--no-color", "--no-log-prefix", "--tail", str(tail), service,
                                    timeout=30, check=False)
        return result.output.strip()

    async def container_id(self, service: str) -> str | None:
        result = await self.compose("ps", "-q", service, check=False)
        lines = result.output.split()
        return lines[0] if result.returncode == 0 and lines else None

    async def down(self) -> None:
        await self.compose("down", "-v", "--remove-orphans", timeout=120, check=False)
