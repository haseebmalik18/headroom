"""Investigation persistence: an append-only event log plus the final outcome."""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from hotpath.agent.investigator import Outcome
from hotpath.agent.state import Event

ROOT = Path(".hotpath/investigations")


class InvestigationStore:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def create(cls, repo: Path, root: Path = ROOT) -> "InvestigationStore":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = Path(root) / f"{stamp}-{Path(repo).resolve().name}"
        path.mkdir(parents=True, exist_ok=True)
        (path / "repo.txt").write_text(str(Path(repo).resolve()))
        return cls(path)

    @classmethod
    def open(cls, ref: str, root: Path = ROOT) -> "InvestigationStore":
        path = Path(ref)
        if not path.is_dir():
            if path.is_absolute() or len(path.parts) > 1:
                raise FileNotFoundError(f"no investigation at {path}")
            matches = sorted(Path(root).glob(f"{ref}*")) if ref != "latest" else sorted(Path(root).iterdir())
            if not matches:
                raise FileNotFoundError(f"no investigation matching {ref!r} in {root}")
            path = matches[-1]
        return cls(path)

    @property
    def repo(self) -> Path:
        return Path((self.path / "repo.txt").read_text())

    def record(self, event: Event) -> None:
        with open(self.path / "events.jsonl", "a") as f:
            f.write(event.model_dump_json() + "\n")

    def events(self) -> list[Event]:
        lines = (self.path / "events.jsonl").read_text().splitlines()
        return [Event.model_validate_json(line) for line in lines]

    def save_outcome(self, outcome: Outcome, model_calls: list | None = None) -> None:
        (self.path / "outcome.json").write_text(outcome.model_dump_json(indent=2))
        if outcome.diff:
            (self.path / "winner.diff").write_text(outcome.diff)
        if model_calls is not None:
            (self.path / "model_calls.json").write_text(
                json.dumps([c.model_dump() for c in model_calls], indent=2)
            )

    def outcome(self) -> Outcome:
        return Outcome.model_validate_json((self.path / "outcome.json").read_text())


def _git(cwd: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, input=stdin, capture_output=True, text=True)


def apply_to_repository(repo: Path, diff: str) -> list[str]:
    """Apply an approved diff to the real repository (the only step that touches it).

    Diff paths are relative to `repo`. When `repo` is a subdirectory of a larger git
    repository, `git apply` run inside it silently skips every path, so we apply from
    the top level with --directory instead, then confirm the files really changed.
    """
    repo = Path(repo).resolve()
    paths = [line[6:] for line in diff.splitlines() if line.startswith("+++ b/")]
    before = {p: (repo / p).read_text() if (repo / p).exists() else None for p in paths}

    inside = _git(repo, "rev-parse", "--show-toplevel")
    if inside.returncode == 0:
        top = Path(inside.stdout.strip())
        prefix = _git(repo, "rev-parse", "--show-prefix").stdout.strip()
        cwd, extra = top, ([f"--directory={prefix.rstrip('/')}"] if prefix else [])
    else:
        cwd, extra = repo, []

    for args in (["apply", "--check", *extra], ["apply", *extra]):
        result = _git(cwd, *args, "-", stdin=diff)
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")

    changed = [p for p in paths if ((repo / p).read_text() if (repo / p).exists() else None) != before[p]]
    if paths and not changed:
        raise RuntimeError("git apply reported success but no file changed")
    return changed
