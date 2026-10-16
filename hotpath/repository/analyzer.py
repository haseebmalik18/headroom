"""Compact repository map for the model.

Rather than sending the whole repository to Nemotron, HotPath sends: the file
tree, dependencies, entrypoints, test names, and the full source of files on the
path of the endpoint under investigation (the file that defines the route plus
the local modules it imports, transitively).
"""

import ast
import re
from pathlib import Path

from pydantic import BaseModel

from hotpath.config import Objective, load_config

SKIP_DIRS = {".git", ".hotpath", "results", "__pycache__", ".pytest_cache", ".venv", "node_modules"}
MAX_FILE_CHARS = 12_000
MAX_RELEVANT_FILES = 8


class SourceFile(BaseModel):
    path: str
    reason: str
    content: str


class RepositoryMap(BaseModel):
    service: str
    objective: Objective
    tree: list[str]
    dependencies: list[str]
    entrypoints: list[str]
    tests: list[str]
    relevant_files: list[SourceFile]

    def render(self) -> str:
        lines = [
            f"# Repository: {self.service}",
            f"Objective: {self.objective.endpoint} {self.objective.metric} < {self.objective.target:g}",
            "",
            "## Files",
            *(f"- {p}" for p in self.tree),
            "",
            "## Dependencies",
            *(f"- {d}" for d in self.dependencies),
            "",
            "## Entrypoints",
            *(f"- {e}" for e in self.entrypoints),
            "",
            "## Tests",
            *(f"- {t}" for t in self.tests),
        ]
        for f in self.relevant_files:
            lines += ["", f"## {f.path} ({f.reason})", "```", f.content.rstrip(), "```"]
        return "\n".join(lines)


def _walk(repo: Path) -> list[Path]:
    files = []
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo)
        if any(part in SKIP_DIRS or part.startswith(".") and part not in {".env.example"} for part in rel.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def _dependencies(repo: Path) -> list[str]:
    deps = []
    for req in sorted(repo.glob("requirements*.txt")):
        deps += [line.strip() for line in req.read_text().splitlines() if line.strip() and not line.startswith("#")]
    return deps


def _entrypoints(repo: Path) -> list[str]:
    found = []
    for dockerfile in sorted(repo.rglob("Dockerfile")):
        for line in dockerfile.read_text().splitlines():
            if line.startswith(("CMD", "ENTRYPOINT")):
                found.append(f"{dockerfile.relative_to(repo)}: {line.strip()}")
    return found


def _tests(repo: Path) -> list[str]:
    names = []
    for path in sorted(repo.glob("tests/**/test_*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                names.append(f"{path.relative_to(repo)}::{node.name}")
    return names


def _local_imports(repo: Path, path: Path) -> list[Path]:
    """Modules inside the repo that `path` imports (relative or package-absolute)."""
    tree = ast.parse(path.read_text())
    package = path.parent
    targets = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = package
            for _ in range(max(node.level - 1, 0)):
                base = base.parent
            if node.level == 0:
                base = repo
            module_parts = node.module.split(".") if node.module else []
            module_path = base.joinpath(*module_parts)
            candidates = [module_path.with_suffix(".py")]
            candidates += [module_path / f"{alias.name}.py" for alias in node.names]
            targets += [c for c in candidates if c.is_file()]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                candidate = repo.joinpath(*alias.name.split(".")).with_suffix(".py")
                if candidate.is_file():
                    targets.append(candidate)
    return targets


def _relevant_files(repo: Path, objective: Objective, files: list[Path]) -> list[SourceFile]:
    method, _, route = objective.endpoint.partition(" ")
    # A route definition such as @app.post("/inventory/reserve") or router.add_api_route("/inventory/reserve", ...).
    pattern = re.compile(rf"\.(?:{method.lower()}|api_route|add_api_route|route)\(\s*[\"']{re.escape(route)}[\"']")
    sources = [f for f in files if f.suffix == ".py" and not f.relative_to(repo).parts[0] == "tests"]
    roots = [f for f in sources if pattern.search(f.read_text())]

    ordered: list[tuple[Path, str]] = [(f, f"defines {objective.endpoint}") for f in roots]
    seen = {f for f in roots}
    queue = list(roots)
    while queue and len(ordered) < MAX_RELEVANT_FILES:
        current = queue.pop(0)
        for dep in _local_imports(repo, current):
            if dep not in seen and dep.name != "__init__.py":
                seen.add(dep)
                queue.append(dep)
                ordered.append((dep, f"imported by {current.relative_to(repo)}"))

    ordered = ordered[:MAX_RELEVANT_FILES]
    ordered += [(f, "database schema") for f in files if f.suffix == ".sql"][:2]
    return [
        SourceFile(path=str(f.relative_to(repo)), reason=reason, content=f.read_text()[:MAX_FILE_CHARS])
        for f, reason in ordered
    ]


def analyze(repo: Path) -> RepositoryMap:
    repo = Path(repo).resolve()
    config = load_config(repo)
    files = _walk(repo)
    return RepositoryMap(
        service=config.service,
        objective=config.objective,
        tree=[str(f.relative_to(repo)) for f in files],
        dependencies=_dependencies(repo),
        entrypoints=_entrypoints(repo),
        tests=_tests(repo),
        relevant_files=_relevant_files(repo, config.objective, files),
    )
