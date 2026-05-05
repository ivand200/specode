from pathlib import Path

from specode.artifacts import ArtifactStore
from specode.schemas import ArtifactStatuses, WorkflowState
from specode.workflow import RepairStopConditions, WorkflowEngine


def write_required_artifacts(store: ArtifactStore, task_name: str) -> None:
    store.write_task_text(task_name, "task.md", "# Task\n")
    store.write_task_text(task_name, "design.md", "# Design\n")
    store.write_task_text(task_name, "tasks.md", "# Tasks\n")


def save_ready_state(store: ArtifactStore, task_name: str) -> WorkflowState:
    state = WorkflowState(
        task_name=task_name,
        task_type="feature",
        artifacts=ArtifactStatuses(
            task="approved",
            research="skipped",
            decision="approved",
            tasks="approved",
        ),
    )
    store.save_task_state(state)
    return state


def test_approve_blocks_when_current_artifact_file_is_missing(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    engine.start("password-reset", "add password reset email flow")

    transition = engine.approve("password-reset")

    assert transition.blocked
    assert transition.state.artifacts.task == "pending-approval"
    assert transition.state.blocker == "Implementation blocked: task.md is missing."
    assert transition.recommended_next_step.startswith("Revise or restore")


def test_approve_current_artifact_advances_to_next_required_stage(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    engine.start("password-reset", "add password reset email flow")
    store.write_task_text("password-reset", "task.md", "# Task\n")

    transition = engine.approve("password-reset")

    assert transition.events == ("approve", "artifact:task:approved", "status")
    assert transition.state.artifacts.task == "approved"
    assert transition.next_stage == "decision"
    assert transition.state.status == "in-progress"


def test_revise_marks_current_artifact_in_progress_and_records_instruction(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    store.save_task_state(
        WorkflowState(
            task_name="audit-log",
            task_type="feature",
            current_stage="decision",
            status="pending-approval",
            artifacts=ArtifactStatuses(
                task="approved",
                research="skipped",
                decision="pending-approval",
                tasks="skipped",
            ),
        )
    )

    transition = engine.revise("audit-log", "tighten the validation plan")

    assert transition.state.artifacts.decision == "in-progress"
    assert transition.state.status == "in-progress"
    assert transition.next_stage == "decision"
    assert "tighten the validation plan" in transition.state.notes[-1]


def test_cancel_stops_workflow_without_deleting_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    store.write_task_text("audit-log", "task.md", "# Task\n")
    engine.start("audit-log", "add audit log")

    transition = engine.cancel("audit-log", "superseded by another task")

    assert transition.blocked
    assert transition.state.blocker == "Task canceled: superseded by another task"
    assert store.task_paths("audit-log").task.exists()
    assert transition.recommended_next_step == "Start or resume another /spec task when ready."


def test_implementation_gate_blocks_missing_approved_artifacts(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    save_ready_state(store, "audit-log")

    transition = engine.check_implementation_gate("audit-log")

    assert transition.blocked
    assert transition.state.current_stage == "task"
    assert transition.state.blocker == "Implementation blocked: task.md is missing."


def test_implementation_gate_requires_research_artifact_only_when_inserted(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    write_required_artifacts(store, "checkout-rounding")
    state = WorkflowState(
        task_name="checkout-rounding",
        task_type="bugfix",
        research_required=True,
        artifacts=ArtifactStatuses(
            task="approved",
            research="approved",
            decision="approved",
            tasks="approved",
        ),
    )
    store.save_task_state(state)

    transition = engine.check_implementation_gate("checkout-rounding")

    assert transition.blocked
    assert transition.state.current_stage == "research"
    assert transition.state.blocker == "Implementation blocked: context.md is missing."


def test_implementation_gate_blocks_stale_artifacts_before_missing_files(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    write_required_artifacts(store, "audit-log")
    state = save_ready_state(store, "audit-log")
    state.artifacts.decision = "stale"
    store.save_task_state(state)

    transition = engine.check_implementation_gate("audit-log")

    assert transition.blocked
    assert transition.state.current_stage == "decision"
    assert transition.state.blocker == "Implementation blocked: design.md is stale and must be revised."


def test_implementation_gate_blocks_unapproved_artifacts(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    write_required_artifacts(store, "audit-log")
    state = save_ready_state(store, "audit-log")
    state.artifacts.tasks = "pending-approval"
    store.save_task_state(state)

    transition = engine.check_implementation_gate("audit-log")

    assert transition.blocked
    assert transition.state.current_stage == "tasks"
    assert transition.state.blocker == "Implementation blocked: tasks.md is pending-approval, not approved."


def test_implementation_approval_requires_ready_gate(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    write_required_artifacts(store, "audit-log")
    save_ready_state(store, "audit-log")

    gate = engine.check_implementation_gate("audit-log")
    approved = engine.approve("audit-log")

    assert gate.next_stage == "implementation"
    assert gate.state.status == "pending-approval"
    assert approved.state.current_stage == "implementation"
    assert approved.state.status == "approved"
    assert approved.recommended_next_step == (
        "Run developer -> tester -> reviewer sequentially unless a stop condition appears."
    )


def test_repair_stops_on_changed_scope_and_new_approval(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    write_required_artifacts(store, "audit-log")
    save_ready_state(store, "audit-log")

    transition = engine.assess_repair(
        "audit-log",
        RepairStopConditions(changed_scope=True, new_approval=True),
    )

    assert transition.blocked
    assert transition.state.current_stage == "implementation"
    assert transition.state.blocker == "Repair blocked: changed scope, new approval."
    assert transition.recommended_next_step == (
        "Return to the manager gate for an explicit decision before repair continues."
    )


def test_repair_stops_on_stale_artifacts(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    write_required_artifacts(store, "audit-log")
    save_ready_state(store, "audit-log")

    transition = engine.assess_repair(
        "audit-log",
        RepairStopConditions(stale_artifacts=True),
    )

    assert transition.blocked
    assert transition.state.blocker == "Repair blocked: stale artifacts."


def test_repair_routes_approved_scope_back_to_developer(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    write_required_artifacts(store, "audit-log")
    save_ready_state(store, "audit-log")

    transition = engine.assess_repair("audit-log")

    assert transition.events == ("repair", "approved-scope", "route:developer", "status")
    assert transition.state.current_stage == "implementation"
    assert transition.state.status == "approved"
    assert transition.recommended_next_step == (
        "Run developer -> tester -> reviewer sequentially unless a stop condition appears."
    )
