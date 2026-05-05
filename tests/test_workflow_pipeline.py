from __future__ import annotations

from pathlib import Path

from specode.artifacts import ArtifactStore
from specode.pydantic_runtime import PydanticAgentRuntime, PydanticRuntimeConfig
from specode.run_store import RunStore
from specode.runtime import FakeAgentRuntime
from specode.schemas import (
    ArtifactStatuses,
    FileOperationSummary,
    RoleRunRequest,
    RoleRunResult,
    WebSearchSummary,
    WorkflowState,
)
from specode.workflow import WorkflowEngine


def write_required_artifacts(store: ArtifactStore, task_name: str) -> None:
    store.write_task_text(task_name, "task.md", "# Task\n")
    store.write_task_text(task_name, "design.md", "# Design\n")
    store.write_task_text(task_name, "tasks.md", "# Tasks\n")


def save_implementation_approved_state(
    store: ArtifactStore,
    task_name: str = "role-pipeline",
) -> None:
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


def test_role_pipeline_completes_after_developer_tester_and_reviewer_pass(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    write_required_artifacts(store, "role-pipeline")
    save_implementation_approved_state(store)
    engine = WorkflowEngine(store)

    result = engine.run_role_pipeline("role-pipeline")

    assert result.done
    assert [record.role for record in result.run_records] == [
        "developer",
        "tester",
        "reviewer",
    ]
    assert [record.role for record in RunStore(store).list_runs("role-pipeline")] == [
        "developer",
        "tester",
        "reviewer",
    ]


def test_tester_failure_routes_repair_through_developer_then_reruns_downstream(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    write_required_artifacts(store, "role-pipeline")
    save_implementation_approved_state(store)
    runtime = FakeAgentRuntime(
        {
            "tester": [
                validation_fail("missing contract coverage"),
                validation_pass(),
            ]
        }
    )

    result = WorkflowEngine(store).run_role_pipeline(
        "role-pipeline",
        runtime=runtime,
    )

    assert result.done
    assert [record.role for record in result.run_records] == [
        "developer",
        "tester",
        "developer",
        "tester",
        "reviewer",
    ]
    assert "repair:tester-fail:route:developer" in result.events


def test_reviewer_changes_route_repair_and_rerun_tester_before_review(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    write_required_artifacts(store, "role-pipeline")
    save_implementation_approved_state(store)
    runtime = FakeAgentRuntime(
        {
            "reviewer": [
                review_changes("review found stale validation claim"),
                review_pass(),
            ]
        }
    )

    result = WorkflowEngine(store).run_role_pipeline(
        "role-pipeline",
        runtime=runtime,
    )

    assert result.done
    assert [record.role for record in result.run_records] == [
        "developer",
        "tester",
        "reviewer",
        "developer",
        "tester",
        "reviewer",
    ]
    assert "repair:reviewer-changes:route:developer" in result.events


def test_blocked_role_stops_pipeline_without_running_later_roles(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    write_required_artifacts(store, "role-pipeline")
    save_implementation_approved_state(store)
    runtime = FakeAgentRuntime({"tester": validation_blocked("missing test credentials")})

    result = WorkflowEngine(store).run_role_pipeline(
        "role-pipeline",
        runtime=runtime,
    )

    assert result.blocked
    assert result.state.current_stage == "testing"
    assert result.state.blocker == "Tester blocked: missing test credentials"
    assert [record.role for record in result.run_records] == ["developer", "tester"]


def test_live_runtime_missing_config_persists_blocked_developer_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    store = ArtifactStore(tmp_path)
    write_required_artifacts(store, "role-pipeline")
    save_implementation_approved_state(store)

    result = WorkflowEngine(store).run_role_pipeline(
        "role-pipeline",
        runtime=PydanticAgentRuntime(PydanticRuntimeConfig.from_env()),
    )

    persisted_runs = RunStore(store).list_runs("role-pipeline")
    assert result.blocked
    assert result.state.current_stage == "implementation"
    assert result.state.blocker == (
        "Developer blocked: OpenAI runtime blocked: OPENAI_API_KEY is not configured."
    )
    assert [record.role for record in result.run_records] == ["developer"]
    assert [record.role for record in persisted_runs] == ["developer"]
    assert persisted_runs[0].status == "blocked"
    assert persisted_runs[0].role_return["result"] == "blocked"


def test_pipeline_blocks_stale_artifacts_instead_of_continuing_silently(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    write_required_artifacts(store, "role-pipeline")
    save_implementation_approved_state(store)
    state = store.load_task_state("role-pipeline")
    state.artifacts.decision = "stale"
    store.save_task_state(state)

    result = WorkflowEngine(store).run_role_pipeline("role-pipeline")

    assert result.blocked
    assert result.run_records == ()
    assert result.state.blocker == "Implementation blocked: design.md is stale and must be revised."


def test_pipeline_rechecks_stale_artifacts_before_repair_pass(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    write_required_artifacts(store, "role-pipeline")
    save_implementation_approved_state(store)
    runtime = StalingTesterRuntime(store)

    result = WorkflowEngine(store).run_role_pipeline(
        "role-pipeline",
        runtime=runtime,
    )

    assert result.blocked
    assert [record.role for record in result.run_records] == ["developer", "tester"]
    assert result.state.blocker == "Implementation blocked: tasks.md is stale and must be revised."


def test_reviewer_pipeline_request_has_workspace_scope_and_receives_tool_summaries(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path)
    write_required_artifacts(store, "role-pipeline")
    save_implementation_approved_state(store)
    runtime = FakeAgentRuntime()

    WorkflowEngine(store).run_role_pipeline(
        "role-pipeline",
        runtime=runtime,
        automation_policy="yolo",
        file_summaries=(
            FileOperationSummary(
                operation="update_file",
                path="src/specode/workflow.py",
                status="ok",
                action="updated",
                changed=True,
            ),
        ),
        web_summaries=(
            WebSearchSummary(
                query="Pydantic AI tool calls",
                status="ok",
                result_count=1,
                sources=["https://pydantic.dev/docs/ai/tools-toolsets/tools/"],
                backend="fake",
            ),
        ),
    )

    reviewer_request = runtime.requests[-1]
    assert reviewer_request.role == "reviewer"
    assert reviewer_request.approved_scope
    assert reviewer_request.automation_policy == "yolo"
    assert reviewer_request.file_summaries[0].path == "src/specode/workflow.py"
    assert reviewer_request.web_summaries[0].query == "Pydantic AI tool calls"
    assert "workspace-scoped" in reviewer_request.instructions
    assert "yolo automation policy" in reviewer_request.instructions
    assert "read-only" not in reviewer_request.instructions


class StalingTesterRuntime(FakeAgentRuntime):
    def __init__(self, store: ArtifactStore) -> None:
        super().__init__({"tester": validation_fail("repair requires refreshed tasks")})
        self.store = store

    def run_role(self, request: RoleRunRequest) -> RoleRunResult:
        result = super().run_role(request)
        if request.role == "tester":
            state = self.store.load_task_state(request.task_name)
            state.artifacts.tasks = "stale"
            self.store.save_task_state(state)
        return result


def validation_pass() -> dict[str, object]:
    return {
        "task": "Task 17",
        "result": "pass",
        "tests_run": ["uv run pytest tests/test_workflow_pipeline.py"],
        "contract_interface_coverage": "pipeline behavior covered",
        "findings": [],
        "test_changes": [],
        "suggested_follow_up_task": "none",
        "suggested_manager_action": "run_reviewer",
        "blocker": "none",
        "notes": [],
    }


def validation_fail(finding: str) -> dict[str, object]:
    return {
        "task": "Task 17",
        "result": "fail",
        "tests_run": ["uv run pytest tests/test_workflow_pipeline.py"],
        "contract_interface_coverage": "failure routed to repair",
        "findings": [finding],
        "test_changes": [],
        "suggested_follow_up_task": "none",
        "suggested_manager_action": "run_developer",
        "blocker": "none",
        "notes": [],
    }


def validation_blocked(blocker: str) -> dict[str, object]:
    return {
        "task": "Task 17",
        "result": "blocked",
        "tests_run": [],
        "contract_interface_coverage": "blocked before validation",
        "findings": [],
        "test_changes": [],
        "suggested_follow_up_task": "none",
        "suggested_manager_action": "mark_blocked",
        "blocker": blocker,
        "notes": [],
    }


def review_pass() -> dict[str, object]:
    return {
        "task": "Task 17",
        "result": "pass",
        "findings": [],
        "interface_contract_findings": [],
        "scope_design_alignment": "aligned",
        "risk_level": "low",
        "suggested_manager_action": "complete_task",
        "blocker": "none",
        "notes": [],
    }


def review_changes(finding: str) -> dict[str, object]:
    return {
        "task": "Task 17",
        "result": "changes_requested",
        "findings": [finding],
        "interface_contract_findings": [],
        "scope_design_alignment": "repair needed inside approved scope",
        "risk_level": "medium",
        "suggested_manager_action": "run_developer",
        "blocker": "none",
        "notes": [],
    }
