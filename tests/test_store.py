import subprocess

import pytest

from hotpath.agent.store import apply_to_repository

DIFF = """diff --git a/app/m.py b/app/m.py
--- a/app/m.py
+++ b/app/m.py
@@ -1 +1 @@
-x = 1
+x = 2
"""


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True)


@pytest.fixture
def nested_repo(tmp_path):
    outer = tmp_path / "outer"
    (outer / "examples" / "svc" / "app").mkdir(parents=True)
    (outer / "examples" / "svc" / "app" / "m.py").write_text("x = 1\n")
    _git(outer, "init", "-q")
    _git(outer, "add", "-A")
    _git(outer, "commit", "-qm", "init")
    return outer / "examples" / "svc"


def test_applies_inside_a_subdirectory_of_a_git_repo(nested_repo):
    changed = apply_to_repository(nested_repo, DIFF)

    assert changed == ["app/m.py"]
    assert (nested_repo / "app" / "m.py").read_text() == "x = 2\n"


def test_applies_outside_any_git_repo(tmp_path):
    repo = tmp_path / "plain"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "m.py").write_text("x = 1\n")

    assert apply_to_repository(repo, DIFF) == ["app/m.py"]
    assert (repo / "app" / "m.py").read_text() == "x = 2\n"


def test_refuses_a_diff_that_does_not_match(nested_repo):
    (nested_repo / "app" / "m.py").write_text("x = 99\n")

    with pytest.raises(RuntimeError, match="git apply"):
        apply_to_repository(nested_repo, DIFF)
    assert (nested_repo / "app" / "m.py").read_text() == "x = 99\n"
