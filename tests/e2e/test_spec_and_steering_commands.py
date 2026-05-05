from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from specode.artifacts import hash_text


def test_user_facing_sdd_commands_create_only_explicit_artifacts(tmp_path: Path) -> None:
    ordinary = run_packaged_specode(tmp_path, "help me inspect this repo\n/exit\n")

    assert ordinary.returncode == 0
    assert "OPENAI_API_KEY" in ordinary.stdout
    assert not (tmp_path / "tasks").exists()
    assert not (tmp_path / "steering").exists()

    source = tmp_path / "incoming" / "auth-reset" / "request.md"
    source.parent.mkdir(parents=True)
    source.write_text(
        "# Add password reset email flow\n\nSend reset links.\n",
        encoding="utf-8",
    )

    sdd = run_packaged_specode(
        tmp_path,
        "\n".join(
            [
                "/spec add password reset email flow",
                "/status",
                "/approve",
                "/spec incoming/auth-reset/request.md",
                "/exit",
                "",
            ]
        ),
    )

    text_task = tmp_path / "tasks" / "add-password-reset-email-flow"
    file_task = tmp_path / "tasks" / "auth-reset"
    text_state = read_state(text_task)
    file_provenance = read_provenance(file_task / "task.md")
    source_text = source.read_text(encoding="utf-8")
    normalized_stdout = normalize_output(sdd.stdout)

    assert sdd.returncode == 0
    assert text_task.joinpath("state.json").exists()
    assert text_task.joinpath("task.md").exists()
    assert text_task.joinpath("runs").is_dir()
    assert file_task.joinpath("state.json").exists()
    assert file_provenance["kind"] == "file"
    assert file_provenance["source_path"] == "incoming/auth-reset/request.md"
    assert file_provenance["source_sha256"] == hash_text(source_text)
    assert "Status for 'add-password-reset-email-flow'" in normalized_stdout
    assert "Next: Create or approve task.md before design, tasks, or implementation." in (
        normalized_stdout
    )
    assert text_state["artifacts"]["task"] == "approved"
    assert text_state["current_stage"] == "decision"
    assert text_state["status"] == "in-progress"
    assert not (tmp_path / "tasks" / "help-me-inspect-this-repo").exists()
    assert not (tmp_path / "steering").exists()

    steering = run_packaged_specode(tmp_path, "/steering\n/exit\n")

    assert steering.returncode == 0
    assert "Created steering docs: product.md, tech.md, structure.md." in normalize_output(
        steering.stdout
    )
    assert (tmp_path / "steering" / "product.md").exists()
    assert (tmp_path / "steering" / "tech.md").exists()
    assert (tmp_path / "steering" / "structure.md").exists()


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


def read_state(task_root: Path) -> dict[str, object]:
    return json.loads(task_root.joinpath("state.json").read_text(encoding="utf-8"))


def read_provenance(task_md: Path) -> dict[str, str | None]:
    match = re.match(
        r"\A<!-- specode-source\n(?P<json>.*?)\n-->",
        task_md.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group("json"))


def normalize_output(output: str) -> str:
    return re.sub(r"\s+", " ", output)
