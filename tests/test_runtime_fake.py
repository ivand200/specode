from __future__ import annotations

import pytest

from specode.runtime import AgentRuntimeError, FakeAgentRuntime
from specode.schemas import (
    CommandRunSummary,
    FileOperationSummary,
    RoleRunRequest,
    TaskReturn,
)


def test_fake_runtime_returns_deterministic_developer_success() -> None:
    runtime = FakeAgentRuntime()
    request = RoleRunRequest(
        task_name="specode-v0-cli-agent",
        role="developer",
        task="Task 16",
        command_summaries=[
            CommandRunSummary(
                command="uv run pytest tests/test_runtime_fake.py",
                status="ok",
                exit_code=0,
                purpose="test",
            )
        ],
        file_summaries=[
            FileOperationSummary(
                operation="create_file",
                path="src/specode/runtime.py",
                status="ok",
                action="created",
                changed=True,
            )
        ],
    )

    result = runtime.run_role(request)

    assert isinstance(result.role_return, TaskReturn)
    assert result.role_return.result == "ready_for_testing"
    assert result.role_return.files_changed == ["src/specode/runtime.py"]


def test_fake_runtime_validates_scripted_role_return() -> None:
    runtime = FakeAgentRuntime(
        {
            "tester": {
                "task": "Task 16",
                "result": "fail",
                "tests_run": ["uv run pytest"],
                "contract_interface_coverage": "runtime contract exercised",
                "findings": ["RunStore did not persist records."],
                "test_changes": [],
                "suggested_follow_up_task": "none",
                "suggested_manager_action": "ask_engineer",
                "blocker": "none",
                "notes": [],
            }
        }
    )

    result = runtime.run_role(
        RoleRunRequest(
            task_name="specode-v0-cli-agent",
            role="tester",
            task="Task 16",
        )
    )

    assert result.role_return.result == "fail"
    assert result.status == "completed"


def test_fake_runtime_rejects_malformed_scripted_return() -> None:
    runtime = FakeAgentRuntime(
        {
            "reviewer": {
                "task": "Task 16",
                "result": "changes_requested",
                "findings": [],
                "interface_contract_findings": [],
                "scope_design_alignment": "not aligned",
                "risk_level": "high",
                "suggested_manager_action": "ask_user",
                "blocker": "none",
                "notes": [],
            }
        }
    )

    with pytest.raises(AgentRuntimeError, match="Malformed reviewer return rejected"):
        runtime.run_role(
            RoleRunRequest(
                task_name="specode-v0-cli-agent",
                role="reviewer",
                task="Task 16",
            )
        )
