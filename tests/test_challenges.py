import json
from pathlib import Path

import pytest

from hotpath.challenges import generate_challenge, fingerprint, TEMPLATES
from hotpath.config import load_config
from hotpath.repository.analyzer import analyze


def test_seed_reproduces_exact_case_without_overwriting(tmp_path):
    a = generate_challenge(42, root=tmp_path)
    b = generate_challenge(42, root=tmp_path)
    assert a.repo != b.repo
    assert a.public == b.public
    assert fingerprint(a.repo) == fingerprint(b.repo) == a.public["fingerprint"]


def test_both_families_vary_data_and_keep_correctness_judges(tmp_path):
    families, datasets = set(), set()
    project = Path(__file__).resolve().parents[1]
    for seed in range(12):
        case = generate_challenge(seed, root=tmp_path)
        manifest = json.loads((case.repo.parent / "manifest.json").read_text())
        families.add(manifest["family"])
        datasets.add(case.public["dataset"])
        source = project / TEMPLATES[manifest["family"]]
        for test in (source / "tests").glob("*.py"):
            assert (case.repo / "tests" / test.name).read_bytes() == test.read_bytes()
        config = load_config(case.repo)
        assert config.workload.concurrency == case.public["concurrency"]
        assert config.objective.model_dump() == case.public["objective"]
        assert "db/*" in config.runtime.protected_paths
        context = analyze(case.repo)
        assert "manifest.json" not in context.tree
        assert not any("reference" in f for f in context.tree)
        assert context.relevant_files
    assert families == {"checkout", "catalog"}
    assert len(datasets) >= 4


@pytest.mark.parametrize("seed", [-1, 2**32, True, "7", 1.2])
def test_invalid_seeds_create_no_files(seed, tmp_path):
    with pytest.raises(ValueError):
        generate_challenge(seed, root=tmp_path)
    assert not list(tmp_path.iterdir())
