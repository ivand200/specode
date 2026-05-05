from __future__ import annotations

import pytest
from pydantic import ValidationError

from specode.schemas import (
    ReviewReturn,
    RoleRunRequest,
    RoleRunResult,
    TaskReturn,
    ValidationReturn,
    WebSearchSummary,
    parse_role_return,
)


def test_developer_task_return_validates_task_return_contract() -> None:
    result = TaskReturn.model_validate(
        {
            "task": "Task 16",
            "result": "ready_for_testing",
            "files_changed": ["src/specode/runtime.py"],
            "checks_run": ["uv run pytest tests/test_runtime_fake.py"],
            "interface_impact": "internal-only",
            "contract_coverage": "Role runtime contract tests added.",
            "suggested_split": "none",
            "suggested_manager_action": "run_tester",
            "blocker": "none",
            "notes": ["ready"],
        }
    )

    assert result.blocker is None
    assert result.suggested_split is None


def test_malformed_developer_return_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_role_return(
            "developer",
            {
                "task": "Task 16",
                "result": "ready_for_testing",
                "interface_impact": "none",
                "contract_coverage": "covered",
                "suggested_manager_action": "mark_blocked",
            },
        )


def test_validation_return_requires_findings_when_tests_fail() -> None:
    with pytest.raises(ValidationError):
        ValidationReturn.model_validate(
            {
                "task": "Task 16",
                "result": "fail",
                "tests_run": ["uv run pytest"],
                "contract_interface_coverage": "fake coverage",
                "findings": [],
                "test_changes": [],
                "suggested_follow_up_task": "none",
                "suggested_manager_action": "ask_engineer",
                "blocker": "none",
                "notes": [],
            }
        )


def test_review_return_requires_findings_when_changes_are_requested() -> None:
    with pytest.raises(ValidationError):
        ReviewReturn.model_validate(
            {
                "task": "Task 16",
                "result": "changes_requested",
                "findings": [],
                "interface_contract_findings": [],
                "scope_design_alignment": "not aligned",
                "risk_level": "medium",
                "suggested_manager_action": "ask_user",
                "blocker": "none",
                "notes": [],
            }
        )


def test_role_run_result_rejects_mismatched_role_return() -> None:
    tester_return = ValidationReturn(
        task="Task 16",
        result="pass",
        tests_run=[],
        contract_interface_coverage="covered",
        findings=[],
        test_changes=[],
        suggested_follow_up_task=None,
        suggested_manager_action="run_reviewer",
        blocker=None,
        notes=[],
    )

    with pytest.raises(ValidationError):
        RoleRunResult(
            task_name="specode-v0-cli-agent",
            role="developer",
            role_return=tester_return,
        )


def test_role_run_request_carries_automation_policy_and_web_summaries() -> None:
    summary = WebSearchSummary(
        query="Pydantic AI tool calls",
        status="ok",
        result_count=1,
        sources=["https://pydantic.dev/docs/ai/tools-toolsets/tools/"],
        backend="fake",
    )

    request = RoleRunRequest(
        task_name="specode-v0-cli-agent",
        role="developer",
        task="Task 16",
        automation_policy="yolo",
        web_summaries=[summary],
    )

    assert request.automation_policy == "yolo"
    assert request.web_summaries == [summary]


def test_role_run_request_rejects_unknown_automation_policy() -> None:
    with pytest.raises(ValidationError):
        RoleRunRequest(
            task_name="specode-v0-cli-agent",
            role="developer",
            task="Task 16",
            automation_policy="auto-edit",
        )


def test_role_run_result_carries_web_summaries() -> None:
    role_return = TaskReturn(
        task="Task 16",
        result="ready_for_testing",
        files_changed=[],
        checks_run=[],
        interface_impact="none",
        contract_coverage="web summary contract carried",
        suggested_manager_action="run_tester",
        blocker=None,
        notes=[],
    )
    summary = WebSearchSummary(
        query="OpenAI web search tool",
        status="ok",
        result_count=1,
        sources=["https://platform.openai.com/docs/"],
        backend="fake",
    )

    result = RoleRunResult(
        task_name="specode-v0-cli-agent",
        role="developer",
        role_return=role_return,
        web_summaries=[summary],
    )

    assert result.web_summaries == [summary]
