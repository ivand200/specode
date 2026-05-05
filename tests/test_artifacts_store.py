from pathlib import Path

import pytest

from specode.artifacts import ArtifactStore, ArtifactStoreError


def test_creates_task_directory_with_runs_and_expected_paths(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    task_dir = store.ensure_task_dir("password-reset")

    paths = store.task_paths("password-reset")
    assert task_dir == tmp_path / "tasks" / "password-reset"
    assert paths.runs.is_dir()
    assert paths.task == tmp_path / "tasks" / "password-reset" / "task.md"


def test_task_text_and_json_round_trip(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    store.write_task_text("checkout-rounding", "task.md", "# Task\n\nSee [design](design.md).\n")
    store.write_task_json("checkout-rounding", {"status": "pending", "schema_version": 1})

    assert store.read_task_text("checkout-rounding", "task.md").startswith("# Task")
    assert store.read_task_json("checkout-rounding") == {
        "schema_version": 1,
        "status": "pending",
    }


def test_run_path_creates_json_path_under_task_runs(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    runs_dir = store.ensure_runs_dir("agent-pipeline")
    run_path = store.run_path("agent-pipeline", "developer-001")

    assert runs_dir == tmp_path / "tasks" / "agent-pipeline" / "runs"
    assert run_path == runs_dir / "developer-001.json"


def test_steering_docs_round_trip_without_task_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    store.write_steering_text("product.md", "# Product\n\nDurable facts.\n")

    assert store.read_steering_text("product.md") == "# Product\n\nDurable facts.\n"
    assert not (tmp_path / "tasks").exists()


@pytest.mark.parametrize(
    "content",
    [
        "[task](/Users/me/project/tasks/example/task.md)",
        "[task](file:///Users/me/project/tasks/example/task.md)",
        "[task]: /Users/me/project/tasks/example/task.md",
        "<file:///Users/me/project/tasks/example/task.md>",
        "[task](C:\\Users\\me\\project\\tasks\\example\\task.md)",
    ],
)
def test_markdown_artifacts_reject_absolute_local_links(
    tmp_path: Path,
    content: str,
) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ArtifactStoreError, match="relative repo links"):
        store.write_task_text("link-policy", "task.md", content)


def test_markdown_artifacts_allow_relative_links_and_web_urls(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    store.write_task_text(
        "link-policy",
        "design.md",
        "[task](task.md)\n[OpenAI](https://openai.com)\n[section](#details)\n",
    )

    assert "https://openai.com" in store.read_task_text("link-policy", "design.md")


@pytest.mark.parametrize("task_name", ["../escape", "/absolute", "bad/name"])
def test_task_paths_reject_names_that_escape_the_workspace(
    tmp_path: Path,
    task_name: str,
) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ArtifactStoreError):
        store.ensure_task_dir(task_name)


def test_raw_write_rejects_paths_outside_workspace(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    with pytest.raises(ArtifactStoreError):
        store.write_text(tmp_path.parent / "outside.md", "# Outside\n")
