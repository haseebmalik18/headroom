"""Isolated candidate workspaces.

Each candidate patch gets a fresh copy of the target repository under
`.hotpath/worktrees/<name>`, with its own git history whose first commit is the
untouched baseline. Patches are applied there, never to the original repo, and
`git diff` against that baseline commit is the reviewable change.
"""

import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel

IGNORED = shutil.ignore_patterns(
    ".git", ".hotpath", "results", "__pycache__", "*.pyc", ".pytest_cache", ".venv", "node_modules", ".DS_Store"
)


class FileChange(BaseModel):
    """The complete new contents of one file, relative to the repository root."""

    path: str
    content: str


class PatchError(RuntimeError):
    pass


def _git(cwd: Path, *args: str, stdin: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-c", "user.name=hotpath", "-c", "user.email=hotpath@localhost", *args],
        cwd=cwd, input=stdin, capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise PatchError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


class Workspace:
    def __init__(self, path: Path):
        self.path = path

    @classmethod
    def create(cls, source: Path, root: Path, name: str) -> "Workspace":
        path = (Path(root) / name).resolve()
        if path.exists():
            shutil.rmtree(path)
        shutil.copytree(Path(source).resolve(), path, ignore=IGNORED)
        _git(path, "init", "-q", "-b", "baseline")
        _git(path, "add", "-A")
        _git(path, "commit", "-q", "--no-verify", "-m", "baseline")
        return cls(path)

    def _resolve(self, relative: str) -> Path:
        target = (self.path / relative).resolve()
        if Path(relative).is_absolute() or not target.is_relative_to(self.path):
            raise PatchError(f"refusing to write {relative!r}: outside the workspace")
        return target

    def write_files(self, changes: list[FileChange]) -> None:
        targets = [(self._resolve(change.path), change) for change in changes]
        for target, change in targets:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.content)

    def apply_patch(self, patch: str) -> None:
        if not patch.endswith("\n"):
            patch += "\n"
        _git(self.path, "apply", "--check", "--whitespace=nowarn", "-", stdin=patch)
        _git(self.path, "apply", "--whitespace=nowarn", "-", stdin=patch)

    def diff(self) -> str:
        _git(self.path, "add", "-A")
        return _git(self.path, "diff", "--cached", "baseline")

    def changed_files(self) -> list[str]:
        _git(self.path, "add", "-A")
        return _git(self.path, "diff", "--cached", "--name-only", "baseline").split()

    def destroy(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
