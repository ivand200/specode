from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from specode.artifacts import ArtifactStore, TaskArtifactPaths
from specode.schemas import WorkflowState


def test_package_cli_and_foundation_artifacts_stay_repo_local(tmp_path: Path) -> None:
    result = run_packaged_specode(tmp_path, "help me inspect this repo\n/exit\n")

    assert result.returncode == 0
    assert "OPENAI_API_KEY" in result.stdout
    assert not (tmp_path / "tasks").exists()

    paths = create_task_skeleton(tmp_path, "foundation-check")

    assert paths.state.exists()
    assert paths.task.exists()
    assert paths.runs.is_dir()
    assert_no_absolute_local_links(paths.root)


def run_packaged_specode(workspace: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    specode = shutil.which("specode")
    assert specode is not None, "specode console script must be installed in the test environment"
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "CHAT_MODEL"):
        env.pop(key, None)

    return subprocess.run(
        [specode],
        cwd=workspace,
        env=env,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def create_task_skeleton(workspace: Path, task_name: str) -> TaskArtifactPaths:
    store = ArtifactStore(workspace)
    state = WorkflowState.new(task_name)

    store.save_task_state(state)
    store.write_task_text(
        task_name,
        "task.md",
        "# Task\n\nFoundation E2E skeleton. See [design](design.md).\n",
    )

    return store.task_paths(task_name)


def assert_no_absolute_local_links(task_root: Path) -> None:
    markdown = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(task_root.glob("*.md"))
    )
    targets = _markdown_targets(markdown)

    assert "file://" not in markdown
    assert all(not target.startswith("/") for target in targets)
    assert all(not re.match(r"^[A-Za-z]:\\", target) for target in targets)


def _markdown_targets(markdown: str) -> list[str]:
    return re.findall(r"\[[^\]]*]\(([^)\s]+)", markdown)
