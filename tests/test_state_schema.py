from pathlib import Path

import pytest
from pydantic import ValidationError

from specode.artifacts import ArtifactStore, ArtifactStoreError
from specode.schemas import ArtifactStatuses, WorkflowState


def test_manager_state_shape_parses_with_decision_design_compatibility() -> None:
    state = WorkflowState.model_validate(
        {
            "schema_version": 1,
            "task_name": "specode-v0",
            "scale": "large",
            "current_stage": "implementation",
            "status": "approved",
            "artifacts": {
                "task": "approved",
                "research": "approved",
                "decision": "approved",
                "tasks": "approved",
            },
            "notes": ["resumed from copied manager state"],
        }
    )

    assert state.artifacts.design == "approved"
    assert state.planning_artifacts_ready()


def test_design_artifact_alias_saves_as_copied_manager_decision_key() -> None:
    statuses = ArtifactStatuses.model_validate(
        {
            "task": "approved",
            "research": "skipped",
            "design": "pending-approval",
            "tasks": "skipped",
        }
    )

    assert statuses.decision == "pending-approval"
    assert "design" not in statuses.model_dump(mode="json")


@pytest.mark.parametrize(
    "patch",
    [
        {"current_stage": "planning"},
        {"status": "waiting"},
        {"scale": "tiny"},
        {"artifacts": {"task": "waiting"}},
        {"schema_version": 2},
    ],
)
def test_invalid_state_values_fail_validation(patch: dict[str, object]) -> None:
    data: dict[str, object] = {"task_name": "checkout-rounding"}
    data.update(patch)

    with pytest.raises(ValidationError):
        WorkflowState.model_validate(data)


def test_missing_state_loads_resume_safe_defaults(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)

    state = store.load_task_state("password-reset")

    assert state == WorkflowState.new("password-reset")
    assert not (tmp_path / "tasks" / "password-reset" / "state.json").exists()


def test_state_save_and_load_round_trip_through_artifact_store(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    state = WorkflowState(
        task_name="auth-flow",
        current_stage="decision",
        status="pending-approval",
        artifacts={
            "task": "approved",
            "research": "skipped",
            "decision": "pending-approval",
            "tasks": "skipped",
        },
    )

    store.save_task_state(state)
    loaded = store.load_task_state("auth-flow")

    assert loaded == state
    assert store.read_task_json("auth-flow")["artifacts"]["decision"] == "pending-approval"


def test_loading_mismatched_state_task_name_fails(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_task_json(
        "actual-task",
        WorkflowState.new("other-task").model_dump(mode="json"),
    )

    with pytest.raises(ArtifactStoreError, match="does not match task directory"):
        store.load_task_state("actual-task")
