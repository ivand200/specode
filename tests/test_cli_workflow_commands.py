from __future__ import annotations

import os
from pathlib import Path

from specode.artifacts import ArtifactStore
from specode.cli import CommandRouter, RouteKind
from specode.runtime import FakeAgentRuntime
from specode.schemas import ArtifactStatuses, WorkflowState


def test_steering_creates_three_docs_without_task_artifacts(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)

    result = router.route("/steering")

    assert result.kind == RouteKind.COMMAND
    assert "Created steering docs: product.md, tech.md, structure.md." in result.text
    assert (tmp_path / "steering" / "product.md").exists()
    assert (tmp_path / "steering" / "tech.md").exists()
    assert (tmp_path / "steering" / "structure.md").exists()
    assert not (tmp_path / "tasks").exists()


def test_steering_preserves_existing_docs(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_steering_text("product.md", "# Product\n\nAlready curated.\n")
    router = CommandRouter(tmp_path)

    result = router.route("/steering")

    assert "Preserved existing: product.md." in result.text
    assert store.read_steering_text("product.md") == "# Product\n\nAlready curated.\n"
    assert (tmp_path / "steering" / "tech.md").exists()
    assert (tmp_path / "steering" / "structure.md").exists()


def test_spec_does_not_create_or_rewrite_steering(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_steering_text("tech.md", "# Tech\n\nKeep this.\n")
    router = CommandRouter(tmp_path)

    result = router.route("/spec add password reset email flow")

    assert "Created /spec task 'add-password-reset-email-flow'" in result.text
    assert store.read_steering_text("tech.md") == "# Tech\n\nKeep this.\n"
    assert not (tmp_path / "steering" / "product.md").exists()
    assert not (tmp_path / "steering" / "structure.md").exists()


def test_status_reports_latest_task_state(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add password reset email flow")

    result = router.route("/status")

    assert result.command == "status"
    assert "Status for 'add-password-reset-email-flow'" in result.text
    assert "Stage: task. Status: pending-approval." in result.text
    assert "Next: Create or approve task.md before design, tasks, or implementation." in result.text


def test_status_without_tasks_is_clear_noop(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)

    result = router.route("/status")

    assert result.text == "No /spec tasks found. Start one with /spec <task description>."
    assert not (tmp_path / "tasks").exists()


def test_status_uses_latest_persisted_task_deterministically(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add first workflow")
    router.route("/spec add second workflow")
    store = ArtifactStore(tmp_path)
    os.utime(store.task_paths("add-first-workflow").state, ns=(1, 1))
    os.utime(store.task_paths("add-second-workflow").state, ns=(2, 2))

    result = router.route("/status")

    assert "Status for 'add-second-workflow'" in result.text


def test_approve_uses_latest_task_and_advances_planning_stage(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add password reset email flow")

    result = router.route("/approve")

    state = ArtifactStore(tmp_path).load_task_state("add-password-reset-email-flow")
    assert "Approval for 'add-password-reset-email-flow'" in result.text
    assert state.artifacts.task == "approved"
    assert state.current_stage == "decision"
    assert state.status == "in-progress"


def test_approve_routes_to_latest_persisted_task(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add first workflow")
    router.route("/spec add second workflow")
    store = ArtifactStore(tmp_path)
    os.utime(store.task_paths("add-first-workflow").state, ns=(1, 1))
    os.utime(store.task_paths("add-second-workflow").state, ns=(2, 2))

    result = router.route("/approve")

    assert "Approval for 'add-second-workflow'" in result.text
    assert store.load_task_state("add-first-workflow").artifacts.task == "pending-approval"


def test_revise_records_instruction_on_latest_task(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add password reset email flow")
    router.route("/approve")

    result = router.route("/revise tighten validation plan")

    state = ArtifactStore(tmp_path).load_task_state("add-password-reset-email-flow")
    assert "Revision for 'add-password-reset-email-flow'" in result.text
    assert state.current_stage == "decision"
    assert state.artifacts.decision == "in-progress"
    assert "tighten validation plan" in state.notes[-1]


def test_revise_routes_to_latest_persisted_task(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add first workflow")
    router.route("/spec add second workflow")
    store = ArtifactStore(tmp_path)
    os.utime(store.task_paths("add-first-workflow").state, ns=(1, 1))
    os.utime(store.task_paths("add-second-workflow").state, ns=(2, 2))

    result = router.route("/revise add clearer acceptance criteria")

    assert "Revision for 'add-second-workflow'" in result.text
    assert "add clearer acceptance criteria" in store.load_task_state("add-second-workflow").notes[-1]


def test_cancel_blocks_latest_task_without_deleting_artifacts(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add password reset email flow")

    result = router.route("/cancel superseded by another task")

    store = ArtifactStore(tmp_path)
    state = store.load_task_state("add-password-reset-email-flow")
    assert "Cancel for 'add-password-reset-email-flow'" in result.text
    assert state.status == "blocked"
    assert state.blocker == "Task canceled: superseded by another task"
    assert store.task_paths("add-password-reset-email-flow").task.exists()


def test_cancel_routes_to_latest_persisted_task(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add first workflow")
    router.route("/spec add second workflow")
    store = ArtifactStore(tmp_path)
    os.utime(store.task_paths("add-first-workflow").state, ns=(1, 1))
    os.utime(store.task_paths("add-second-workflow").state, ns=(2, 2))

    result = router.route("/cancel duplicate request")

    assert "Cancel for 'add-second-workflow'" in result.text
    assert store.load_task_state("add-first-workflow").status == "pending-approval"


def test_run_live_uses_pydantic_runtime_from_env(
    tmp_path: Path,
    monkeypatch,
) -> None:
    save_implementation_approved_task(tmp_path, "live-role-pipeline")
    calls: list[tuple[str, object]] = []

    class DummyConfig:
        @classmethod
        def from_env(cls, **kwargs: object) -> str:
            calls.append(("config", kwargs))
            return "live-config"

    class DummyRuntime(FakeAgentRuntime):
        def __init__(self, config: object) -> None:
            calls.append(("runtime", config))
            super().__init__()

    monkeypatch.setattr("specode.cli.PydanticRuntimeConfig", DummyConfig)
    monkeypatch.setattr("specode.cli.PydanticAgentRuntime", DummyRuntime)

    result = CommandRouter(tmp_path).route("/run live")

    state = ArtifactStore(tmp_path).load_task_state("live-role-pipeline")
    assert result.command == "run"
    assert "Pipeline for 'live-role-pipeline'" in result.text
    assert "Status: done" in result.text
    assert calls == [
        ("config", {"dotenv_path": tmp_path / ".env"}),
        ("runtime", "live-config"),
    ]
    assert state.status == "done"


def test_run_rejects_unknown_scenario_and_mentions_live(tmp_path: Path) -> None:
    result = CommandRouter(tmp_path).route("/run production")

    assert result.command == "run"
    assert result.text == (
        "Usage: /run [fake|live|fake-tester-fail|fake-reviewer-changes|"
        "fake-policy-block]"
    )


def save_implementation_approved_task(workspace: Path, task_name: str) -> None:
    store = ArtifactStore(workspace)
    store.write_task_text(task_name, "task.md", "# Task\n")
    store.write_task_text(task_name, "design.md", "# Design\n")
    store.write_task_text(task_name, "tasks.md", "# Tasks\n")
    store.save_task_state(
        WorkflowState(
            task_name=task_name,
            task_type="feature",
            current_stage="implementation",
            status="approved",
            artifacts=ArtifactStatuses(
                task="approved",
                research="skipped",
                decision="approved",
                tasks="approved",
            ),
        )
    )
