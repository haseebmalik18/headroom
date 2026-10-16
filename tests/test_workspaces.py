import pytest

from hotpath.execution.worktrees import FileChange, PatchError, Workspace


@pytest.fixture
def source(tmp_path):
    repo = tmp_path / "service"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "inventory.py").write_text("LOCK = 'global'\n\ndef reserve():\n    return LOCK\n")
    (repo / "README.md").write_text("# service\n")
    (repo / "results").mkdir()
    (repo / "results" / "old.json").write_text("{}")
    (repo / "app" / "__pycache__").mkdir()
    (repo / "app" / "__pycache__" / "x.pyc").write_bytes(b"\0")
    return repo


def test_create_copies_source_without_artifacts(source, tmp_path):
    ws = Workspace.create(source, tmp_path / "worktrees", "candidate-a")

    assert (ws.path / "app" / "inventory.py").read_text().startswith("LOCK = 'global'")
    assert not (ws.path / "results").exists()
    assert not (ws.path / "app" / "__pycache__").exists()
    assert ws.diff() == ""


def test_workspace_never_touches_the_source(source, tmp_path):
    ws = Workspace.create(source, tmp_path / "worktrees", "candidate-a")

    ws.write_files([FileChange(path="app/inventory.py", content="LOCK = 'per-sku'\n")])

    assert (source / "app" / "inventory.py").read_text().startswith("LOCK = 'global'")


def test_write_files_produces_a_diff(source, tmp_path):
    ws = Workspace.create(source, tmp_path / "worktrees", "candidate-a")

    ws.write_files([
        FileChange(path="app/inventory.py", content="LOCK = 'per-sku'\n\ndef reserve():\n    return LOCK\n"),
        FileChange(path="app/locks.py", content="def lock_for(sku):\n    ...\n"),
    ])
    diff = ws.diff()

    assert "-LOCK = 'global'" in diff
    assert "+LOCK = 'per-sku'" in diff
    assert "app/locks.py" in diff
    assert ws.changed_files() == ["app/inventory.py", "app/locks.py"]


def test_apply_patch(source, tmp_path):
    donor = Workspace.create(source, tmp_path / "worktrees", "donor")
    donor.write_files([FileChange(path="app/inventory.py", content="LOCK = 'atomic'\n")])
    patch = donor.diff()

    ws = Workspace.create(source, tmp_path / "worktrees", "candidate-b")
    ws.apply_patch(patch)

    assert (ws.path / "app" / "inventory.py").read_text() == "LOCK = 'atomic'\n"


def test_bad_patch_raises_and_leaves_workspace_clean(source, tmp_path):
    ws = Workspace.create(source, tmp_path / "worktrees", "candidate-c")

    with pytest.raises(PatchError):
        ws.apply_patch("--- a/app/nope.py\n+++ b/app/nope.py\n@@ -1 +1 @@\n-x\n+y\n")

    assert ws.diff() == ""


@pytest.mark.parametrize("path", ["../escape.py", "/etc/passwd", "app/../../escape.py"])
def test_write_files_rejects_paths_outside_workspace(source, tmp_path, path):
    ws = Workspace.create(source, tmp_path / "worktrees", "candidate-d")

    with pytest.raises(PatchError, match="outside"):
        ws.write_files([FileChange(path=path, content="x")])


def test_destroy_removes_workspace(source, tmp_path):
    ws = Workspace.create(source, tmp_path / "worktrees", "candidate-e")
    ws.destroy()

    assert not ws.path.exists()


def test_create_replaces_stale_workspace(source, tmp_path):
    first = Workspace.create(source, tmp_path / "worktrees", "same")
    (first.path / "junk.txt").write_text("stale")

    second = Workspace.create(source, tmp_path / "worktrees", "same")

    assert not (second.path / "junk.txt").exists()
