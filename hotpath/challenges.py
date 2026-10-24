"""Seeded variations of benchmark fixtures, generated before the solver starts.

The manifest is a sibling of the target repo, never part of the model's context.
These are randomized cases from known bug families, not arbitrary new programs.
"""

import hashlib
import json
import random
import secrets
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import yaml

from hotpath.config import load_config

PROJECT = Path(__file__).resolve().parents[1]
VERSION = 1
MAX_SEED = 2**32 - 1
FAMILIES = ("checkout", "catalog")
TEMPLATES = {"checkout": "examples/checkout-service", "catalog": "evals/scenarios/catalog-service"}


def fingerprint(repo: Path) -> str:
    digest = hashlib.sha256()
    for file in sorted(p for p in repo.rglob("*") if p.is_file()):
        digest.update(file.relative_to(repo).as_posix().encode() + b"\0")
        digest.update(file.read_bytes() + b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class Challenge:
    repo: Path
    public: dict


def _replace(file: Path, before: str, after: str) -> None:
    text = file.read_text()
    if text.count(before) != 1:
        raise ValueError(f"Challenge template changed: expected one {before!r} in {file.name}")
    file.write_text(text.replace(before, after))


def generate_challenge(seed: int | None = None, *, root: Path = Path(".hotpath/challenges"),
                       project: Path = PROJECT) -> Challenge:
    seed = secrets.randbits(32) if seed is None else seed
    if type(seed) is not int or not 0 <= seed <= MAX_SEED:
        raise ValueError(f"seed must be an integer between 0 and {MAX_SEED}")
    rng = random.Random(seed)
    family = rng.choice(FAMILIES)
    source = project / TEMPLATES[family]
    case = root / uuid4().hex
    repo = case / "service"
    repo.mkdir(parents=True, exist_ok=False)

    # Copy only the fixture's runtime files: no README, reference fix, manifest,
    # local environment, previous results, or repository history.
    for name in ("app", "db", "tests", "load"):
        shutil.copytree(source / name, repo / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))
    for name in ("Dockerfile", "docker-compose.yml", "hotpath.yaml", "pyproject.toml",
                 "requirements.txt", "requirements-dev.txt"):
        shutil.copyfile(source / name, repo / name)

    config = yaml.safe_load((repo / "hotpath.yaml").read_text())
    config["service"] = f"challenge-{seed}"
    delay = rng.choice((500, 650, 800))
    _replace(repo / "docker-compose.yml", "${DB_NETWORK_DELAY:-500us}", f"{delay}us")
    if family == "checkout":
        products = rng.choice((750, 1000, 1500, 2000))
        concurrency = rng.choice((400, 450, 500))
        think_ms = rng.choice((1800, 2000, 2200))
        _replace(repo / "db/schema.sql", "generate_series(1, 1000)", f"generate_series(1, {products})")
        _replace(repo / "load/reserve.js", "__ENV.SKU_COUNT || '1000'", f"__ENV.SKU_COUNT || '{products}'")
        title = "Checkout under load"
        dataset = f"{products:,} products"
    else:
        per_category = rng.choice((30, 40, 50, 60))
        concurrency = rng.choice((60, 80, 100))
        think_ms = rng.choice((1000, 1200, 1500))
        _replace(repo / "db/schema.sql", "(i - 1) / 40", f"(i - 1) / {per_category}")
        _replace(repo / "db/schema.sql", "generate_series(1, 2000)", f"generate_series(1, {50 * per_category})")
        _replace(repo / "db/schema.sql", "setseed(0.42)", f"setseed({rng.uniform(-1, 1):.8f})")
        title = "Catalog under load"
        dataset = f"50 categories · {per_category} products each"

    config["workload"].update(concurrency=concurrency, think_ms=think_ms)
    # The data and dependency definitions are part of the challenge, not an
    # optimization surface. Existing correctness tests remain unchanged.
    config["runtime"]["protected_paths"] += ["db/*", "requirements*.txt", "pyproject.toml"]
    (repo / "hotpath.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    parsed = load_config(repo)
    public = {
        "version": VERSION, "seed": seed, "title": title, "dataset": dataset,
        "concurrency": concurrency, "think_ms": think_ms,
        "objective": parsed.objective.model_dump(), "fingerprint": fingerprint(repo),
    }
    # Only public is sent to the page. The solver receives the service repo.
    (case / "manifest.json").write_text(json.dumps({
        **public, "family": family, "template": TEMPLATES[family], "db_delay_us": delay,
    }, indent=2) + "\n")
    return Challenge(repo, public)
