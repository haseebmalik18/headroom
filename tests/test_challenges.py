import json
from pathlib import Path

import pytest

from headroom.challenges import generate_challenge, fingerprint, TEMPLATES
from headroom.config import load_config
from headroom.repository.analyzer import analyze


def test_seed_reproduces_exact_case_without_overwriting(tmp_path):
    a = generate_challenge(42, root=tmp_path)
    b = generate_challenge(42, root=tmp_path)
    assert a.repo != b.repo
    assert a.public == b.public
    assert fingerprint(a.repo) == fingerprint(b.repo) == a.public["fingerprint"]


def test_all_families_vary_data_and_keep_correctness_judges(tmp_path):
    families, datasets = set(), set()
    project = Path(__file__).resolve().parents[1]
    concurrency = {
        "checkout": {650, 700, 750}, "catalog": {160, 180, 200},
        "auth": {180, 200, 220}, "dashboard": {5, 6, 8}, "pricing": {180, 200, 220},
    }
    for seed, selected_family in enumerate(TEMPLATES):
        case = generate_challenge(seed, family=selected_family, root=tmp_path)
        manifest = json.loads((case.repo.parent / "manifest.json").read_text())
        families.add(manifest["family"])
        assert case.public["failure"] == manifest["family"]
        assert case.public["concurrency"] in concurrency[manifest["family"]]
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
    assert families == set(TEMPLATES)
    assert len(datasets) >= 4


@pytest.mark.parametrize("family", TEMPLATES)
def test_allowlisted_failure_mode_selects_family_without_entering_repo(family, tmp_path):
    case = generate_challenge(42, family=family, root=tmp_path)
    assert case.public["failure"] == family
    assert json.loads((case.repo.parent / "manifest.json").read_text())["family"] == family
    assert "failure:" not in (case.repo / "headroom.yaml").read_text()


@pytest.mark.parametrize("seed", [-1, 2**32, True, "7", 1.2])
def test_invalid_seeds_create_no_files(seed, tmp_path):
    with pytest.raises(ValueError):
        generate_challenge(seed, root=tmp_path)
    assert not list(tmp_path.iterdir())


def test_unknown_failure_mode_creates_no_files(tmp_path):
    with pytest.raises(ValueError):
        generate_challenge(7, family="visitor-command", root=tmp_path)
    assert not list(tmp_path.iterdir())
