"""Agent and chat runtime boundaries with deterministic fake role runner."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from specode.schemas import (
    ReviewReturn,
    RoleName,
    RoleRunRequest,
    RoleRunResult,
    TaskReturn,
    ValidationReturn,
    parse_role_return,
)


class AgentRuntimeError(ValueError):
    """Raised when a role runtime cannot produce a valid structured result."""


@dataclass(frozen=True)
class ChatRequest:
    """Plain chat input routed outside slash-command workflows."""

    message: str


@dataclass(frozen=True)
class ChatResult:
    """Plain chat response returned by a chat runtime."""

    text: str
    status: str = "completed"
    blocker: str | None = None


class ChatRuntime(ABC):
    """Chat execution abstraction used by CLI routing."""

    @abstractmethod
    def run_chat(self, request: ChatRequest) -> ChatResult:
        """Run one plain chat turn and return assistant text."""


class FakeChatRuntime(ChatRuntime):
    """Deterministic chat runtime for local fallback and tests."""

    def __init__(self, response: str | None = None) -> None:
        self.response = response or (
            "Normal chat mode is active. V0 is deterministic here, so no SDD "
            "artifacts were created."
        )
        self.requests: list[ChatRequest] = []

    def run_chat(self, request: ChatRequest) -> ChatResult:
        validated_request = ChatRequest(message=request.message)
        self.requests.append(validated_request)
        return ChatResult(text=self.response)


class AgentRuntime(ABC):
    """Role execution abstraction used by workflow code."""

    @abstractmethod
    def run_role(self, request: RoleRunRequest) -> RoleRunResult:
        """Run one role and return a validated role result."""


def role_return_model(
    role: RoleName,
) -> type[TaskReturn] | type[ValidationReturn] | type[ReviewReturn]:
    """Return the structured output model expected for a role."""

    model_by_role: dict[
        RoleName,
        type[TaskReturn] | type[ValidationReturn] | type[ReviewReturn],
    ] = {
        "developer": TaskReturn,
        "tester": ValidationReturn,
        "reviewer": ReviewReturn,
    }
    return model_by_role[role]


def blocked_role_return_payload(
    request: RoleRunRequest,
    blocker: str,
) -> dict[str, Any]:
    """Build a valid blocked role return while preserving the runtime contract."""

    payloads = {
        "developer": _blocked_developer_payload,
        "tester": _blocked_tester_payload,
        "reviewer": _blocked_reviewer_payload,
    }
    return payloads[request.role](request, blocker)


class FakeAgentRuntime(AgentRuntime):
    """Deterministic role runtime for tests and the V0 local pipeline.

    The fake never calls a live model and never executes tools. It either
    validates caller-provided scripted payloads or produces stable success
    returns for the requested role.
    """

    def __init__(
        self,
        scripted_returns: Mapping[RoleName, object] | None = None,
    ) -> None:
        self._scripted_returns: dict[RoleName, list[object]] = {}
        self.requests: list[RoleRunRequest] = []
        for role, payload in (scripted_returns or {}).items():
            if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, dict)):
                self._scripted_returns[role] = [deepcopy(item) for item in payload]
            else:
                self._scripted_returns[role] = [deepcopy(payload)]

    def run_role(self, request: RoleRunRequest) -> RoleRunResult:
        validated_request = RoleRunRequest.model_validate(request)
        self.requests.append(validated_request)
        payload = self._payload_for(validated_request)

        try:
            role_return = parse_role_return(validated_request.role, payload)
        except ValidationError as exc:
            raise AgentRuntimeError(
                f"Malformed {validated_request.role} return rejected."
            ) from exc

        status = "blocked" if role_return.result == "blocked" else "completed"
        return RoleRunResult(
            task_name=validated_request.task_name,
            role=validated_request.role,
            status=status,
            role_return=role_return,
            command_summaries=validated_request.command_summaries,
            file_summaries=validated_request.file_summaries,
            web_summaries=validated_request.web_summaries,
            blocker=getattr(role_return, "blocker", None),
        )

    def _payload_for(self, request: RoleRunRequest) -> object:
        scripted = self._scripted_returns.get(request.role)
        if scripted:
            if len(scripted) == 1:
                return deepcopy(scripted[0])
            return deepcopy(scripted.pop(0))
        return _default_payload(request)


def _default_payload(request: RoleRunRequest) -> dict[str, Any]:
    defaults = {
        "developer": _developer_payload,
        "tester": _tester_payload,
        "reviewer": _reviewer_payload,
    }
    return defaults[request.role](request)


def _developer_payload(request: RoleRunRequest) -> dict[str, Any]:
    return TaskReturn(
        task=request.task,
        result="ready_for_testing",
        files_changed=[
            summary.path
            for summary in request.file_summaries
            if summary.status == "ok" and summary.action in {"created", "updated", "deleted"}
        ],
        checks_run=[
            summary.command
            for summary in request.command_summaries
            if summary.purpose in {"test", "lint", "build"}
        ],
        interface_impact="none",
        contract_coverage="No live implementation was performed by FakeAgentRuntime.",
        suggested_split=None,
        suggested_manager_action="run_tester",
        blocker=None,
        notes=["FakeAgentRuntime developer return."],
    ).model_dump(mode="json")


def _tester_payload(request: RoleRunRequest) -> dict[str, Any]:
    tests_run = [
        summary.command
        for summary in request.command_summaries
        if summary.purpose == "test" or "pytest" in summary.command
    ]
    return ValidationReturn(
        task=request.task,
        result="pass",
        tests_run=tests_run,
        contract_interface_coverage=(
            "FakeAgentRuntime did not execute tests; supplied command summaries "
            "were preserved."
        ),
        findings=[],
        test_changes=[
            summary.path
            for summary in request.file_summaries
            if summary.status == "ok" and summary.action in {"created", "updated"}
        ],
        suggested_follow_up_task=None,
        suggested_manager_action="run_reviewer",
        blocker=None,
        notes=["FakeAgentRuntime tester return."],
    ).model_dump(mode="json")


def _reviewer_payload(request: RoleRunRequest) -> dict[str, Any]:
    return ReviewReturn(
        task=request.task,
        result="pass",
        findings=[],
        interface_contract_findings=[],
        scope_design_alignment="FakeAgentRuntime found no deterministic scope drift.",
        risk_level="low",
        suggested_manager_action="complete_task",
        blocker=None,
        notes=["FakeAgentRuntime reviewer return."],
    ).model_dump(mode="json")


def _blocked_developer_payload(
    request: RoleRunRequest,
    blocker: str,
) -> dict[str, Any]:
    return TaskReturn(
        task=request.task,
        result="blocked",
        files_changed=[],
        checks_run=[],
        interface_impact="none",
        contract_coverage="No implementation was performed because runtime was blocked.",
        suggested_split=None,
        suggested_manager_action="mark_blocked",
        blocker=blocker,
        notes=[],
    ).model_dump(mode="json")


def _blocked_tester_payload(
    request: RoleRunRequest,
    blocker: str,
) -> dict[str, Any]:
    return ValidationReturn(
        task=request.task,
        result="blocked",
        tests_run=[],
        contract_interface_coverage=(
            "No validation was performed because runtime was blocked."
        ),
        findings=[],
        test_changes=[],
        suggested_follow_up_task=None,
        suggested_manager_action="mark_blocked",
        blocker=blocker,
        notes=[],
    ).model_dump(mode="json")


def _blocked_reviewer_payload(
    request: RoleRunRequest,
    blocker: str,
) -> dict[str, Any]:
    return ReviewReturn(
        task=request.task,
        result="blocked",
        findings=[],
        interface_contract_findings=[],
        scope_design_alignment="No review was performed because runtime was blocked.",
        risk_level="medium",
        suggested_manager_action="ask_user",
        blocker=blocker,
        notes=[],
    ).model_dump(mode="json")
