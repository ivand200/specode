from pathlib import Path

from specode.artifacts import ArtifactStore
from specode.schemas import ArtifactStatuses, WorkflowState
from specode.workflow import WorkflowEngine


def test_new_feature_records_classification_and_skips_research(tmp_path: Path) -> None:
    engine = WorkflowEngine(ArtifactStore(tmp_path))

    transition = engine.start("password-reset", "add password reset email flow")

    assert transition.events == (
        "new",
        "classification:feature",
        "research:skipped",
        "status",
    )
    assert transition.state.task_type == "feature"
    assert transition.classification is not None
    assert transition.classification.requirements_shape == "task-requirements"
    assert transition.state.artifacts.research == "skipped"


def test_clear_bugfix_inserts_research_when_root_cause_evidence_is_needed(
    tmp_path: Path,
) -> None:
    engine = WorkflowEngine(ArtifactStore(tmp_path))

    transition = engine.start(
        "checkout-rounding",
        "fix checkout total rounding regression",
    )

    assert transition.events == (
        "new",
        "classification:bugfix",
        "research:inserted",
        "status",
    )
    assert transition.classification is not None
    assert transition.classification.requirements_shape == "bugfix-spec"
    assert transition.state.research_required


def test_inserted_research_routes_after_task_approval(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    state = engine.start(
        "checkout-rounding",
        "fix checkout total rounding regression",
    ).state
    state.artifacts.task = "approved"
    store.save_task_state(state)

    transition = engine.status("checkout-rounding")

    assert transition.next_stage == "research"
    assert transition.state.status == "in-progress"


def test_ambiguous_classification_blocks_before_task_artifact_is_written(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)

    transition = engine.start("login-flow", "improve the login flow")

    assert transition.blocked
    assert transition.state.pending_questions == [
        "Is this /spec request a new feature or a bugfix for existing behavior?"
    ]
    assert not store.task_paths("login-flow").task.exists()


def test_start_resumes_existing_task_without_reclassifying(tmp_path: Path) -> None:
    engine = WorkflowEngine(ArtifactStore(tmp_path))
    engine.start("password-reset", "add password reset email flow")

    transition = engine.start("password-reset", "fix password reset bug")

    assert transition.events == ("resume", "status")
    assert transition.state.task_type == "feature"


def test_v0_routing_requires_task_design_and_tasks_before_implementation(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    engine = WorkflowEngine(store)
    store.save_task_state(
        WorkflowState(
            task_name="audit-log",
            task_type="feature",
            artifacts=ArtifactStatuses(
                task="approved",
                research="skipped",
                decision="skipped",
                tasks="skipped",
            ),
        )
    )

    design_transition = engine.status("audit-log")
    state = design_transition.state
    state.artifacts.decision = "approved"
    store.save_task_state(state)
    tasks_transition = engine.status("audit-log")
    state = tasks_transition.state
    state.artifacts.tasks = "approved"
    store.save_task_state(state)
    implementation_transition = engine.status("audit-log")

    assert design_transition.next_stage == "decision"
    assert tasks_transition.next_stage == "tasks"
    assert implementation_transition.next_stage == "implementation"
    assert implementation_transition.state.planning_artifacts_ready()
