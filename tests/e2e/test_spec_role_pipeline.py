from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path


def test_role_pipeline_boundary_runs_repairs_and_policy_block(
    tmp_path: Path,
) -> None:
    happy = prepare_approved_task(tmp_path / "happy", "add happy role pipeline")
    happy_run = run_packaged_specode(happy.workspace, "/run fake\n/exit\n")

    assert happy_run.returncode == 0
    assert "Pipeline for 'add-happy-role-pipeline'" in normalize_output(happy_run.stdout)
    assert "Status: done" in normalize_output(happy_run.stdout)
    assert read_run_roles(happy.task_root) == ["developer", "tester", "reviewer"]
    assert read_state(happy.task_root)["status"] == "done"

    tester_repair = prepare_approved_task(
        tmp_path / "tester-repair",
        "add tester repair role pipeline",
    )
    tester_run = run_packaged_specode(
        tester_repair.workspace,
        "/run fake-tester-fail\n/exit\n",
    )

    assert tester_run.returncode == 0
    assert "repair:tester-fail:route:developer" in normalize_output(tester_run.stdout)
    assert read_run_roles(tester_repair.task_root) == [
        "developer",
        "tester",
        "developer",
        "tester",
        "reviewer",
    ]
    assert read_state(tester_repair.task_root)["status"] == "done"

    reviewer_repair = prepare_approved_task(
        tmp_path / "reviewer-repair",
        "add reviewer repair role pipeline",
    )
    reviewer_run = run_packaged_specode(
        reviewer_repair.workspace,
        "/run fake-reviewer-changes\n/exit\n",
    )

    assert reviewer_run.returncode == 0
    assert "repair:reviewer-changes:route:developer" in normalize_output(
        reviewer_run.stdout
    )
    assert read_run_roles(reviewer_repair.task_root) == [
        "developer",
        "tester",
        "reviewer",
        "developer",
        "tester",
        "reviewer",
    ]
    assert read_state(reviewer_repair.task_root)["status"] == "done"

    policy_block = prepare_approved_task(
        tmp_path / "policy-block",
        "add policy block role pipeline",
    )
    blocked_run = run_packaged_specode(
        policy_block.workspace,
        "/run fake-policy-block\n/exit\n",
    )
    blocked_state = read_state(policy_block.task_root)
    blocked_runs = read_runs(policy_block.task_root)

    assert blocked_run.returncode == 0
    assert "Policy blocked file mutation" in normalize_output(blocked_run.stdout)
    assert blocked_state["status"] == "blocked"
    assert blocked_state["current_stage"] == "implementation"
    assert blocked_state["blocker"] == (
        "Developer blocked: Policy blocked file mutation: write denied by read-only policy."
    )
    assert [record["role"] for record in blocked_runs] == ["developer"]
    assert blocked_runs[0]["status"] == "blocked"
    assert blocked_runs[0]["role_return"]["result"] == "blocked"
    assert blocked_runs[0]["files"][0]["status"] == "blocked"
    assert blocked_runs[0]["files"][0]["blocker"] == (
        "Policy blocked file mutation: write denied by read-only policy."
    )


class ApprovedTask:
    def __init__(self, workspace: Path, task_name: str) -> None:
        self.workspace = workspace
        self.task_name = task_name
        self.task_root = workspace / "tasks" / task_name


def prepare_approved_task(workspace: Path, request: str) -> ApprovedTask:
    workspace.mkdir()
    task_name = slugify(request)

    created = run_packaged_specode(
        workspace,
        "\n".join(
            [
                f"/spec {request}",
                "/approve",
                "/exit",
                "",
            ]
        ),
    )

    assert created.returncode == 0
    task_root = workspace / "tasks" / task_name
    assert task_root.joinpath("task.md").exists()
    task_root.joinpath("design.md").write_text(
        "# Design\n\nApproved fake role pipeline design.\n",
        encoding="utf-8",
    )
    task_root.joinpath("tasks.md").write_text(
        "# Tasks\n\n- Run the fake role pipeline.\n",
        encoding="utf-8",
    )

    approved = run_packaged_specode(
        workspace,
        "\n".join(
            [
                "/approve",
                "/approve",
                "/approve",
                "/exit",
                "",
            ]
        ),
    )

    assert approved.returncode == 0
    state = read_state(task_root)
    assert state["current_stage"] == "implementation"
    assert state["status"] == "approved"
    return ApprovedTask(workspace, task_name)


def run_packaged_specode(workspace: Path, stdin: str) -> subprocess.CompletedProcess[str]:
    specode = shutil.which("specode")
    assert specode is not None, "specode console script must be installed in the test environment"

    return subprocess.run(
        [specode],
        cwd=workspace,
        input=stdin,
        text=True,
        capture_output=True,
        check=False,
    )


def read_state(task_root: Path) -> dict[str, object]:
    return json.loads(task_root.joinpath("state.json").read_text(encoding="utf-8"))


def read_runs(task_root: Path) -> list[dict[str, object]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(task_root.joinpath("runs").glob("*.json"))
    ]


def read_run_roles(task_root: Path) -> list[str]:
    return [str(record["role"]) for record in read_runs(task_root)]


def normalize_output(output: str) -> str:
    return re.sub(r"\s+", " ", output)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
