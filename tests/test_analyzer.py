from pathlib import Path

from headroom.repository.analyzer import analyze

CHECKOUT = Path(__file__).resolve().parents[1] / "examples" / "checkout-service"


def test_map_finds_endpoint_handler_and_its_local_imports():
    repo_map = analyze(CHECKOUT)

    relevant = [f.path for f in repo_map.relevant_files]
    assert relevant[0] == "app/main.py"            # defines POST /inventory/reserve
    assert "app/inventory.py" in relevant          # imported by main.py
    assert "app/db.py" in relevant
    assert "db/schema.sql" in relevant
    assert all(not p.startswith(("tests/", "scripts/")) for p in relevant)


def test_map_lists_tests_dependencies_and_entrypoints():
    repo_map = analyze(CHECKOUT)

    assert "tests/test_inventory_concurrency.py::test_concurrent_reservations_never_oversell" in repo_map.tests
    assert any(d.startswith("asyncpg") for d in repo_map.dependencies)
    assert any("uvicorn" in e for e in repo_map.entrypoints)
    assert "app/inventory.py" in repo_map.tree
    assert repo_map.objective.endpoint == "POST /inventory/reserve"


def test_map_excludes_headroom_artifacts(tmp_path):
    repo_map = analyze(CHECKOUT)

    assert not any(p.startswith(("results/", ".headroom/")) for p in repo_map.tree)


def test_render_is_compact_and_contains_source():
    text = analyze(CHECKOUT).render()

    assert "POST /inventory/reserve" in text
    assert "async def reserve(" in text
    assert len(text) < 40_000
