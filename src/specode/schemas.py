"""Pydantic schemas for SpeCode workflow state and role returns."""

from __future__ import annotations

import re
from typing import Literal, Self, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SCHEMA_VERSION = 1

TaskType = Literal["feature", "bugfix"]
Stage = Literal[
    "task",
    "research",
    "decision",
    "tasks",
    "implementation",
    "testing",
    "review",
    "done",
]
Status = Literal[
    "in-progress",
    "pending-approval",
    "approved",
    "skipped",
    "blocked",
    "done",
    "stale",
]
Scale = Literal["low", "medium", "large"]
ArtifactName = Literal["task", "research", "decision", "tasks"]
RoleName = Literal["developer", "tester", "reviewer"]
AutomationPolicy = Literal["approved", "yolo"]
TaskReturnResult = Literal["ready_for_testing", "needs_split", "blocked"]
ValidationReturnResult = Literal["pass", "fail", "blocked"]
ReviewReturnResult = Literal["pass", "changes_requested", "blocked"]
InterfaceImpact = Literal["none", "internal-only", "public-contract"]
DeveloperManagerAction = Literal[
    "ask_engineer",
    "run_tester",
    "split_tasks",
    "mark_blocked",
]
TesterManagerAction = Literal[
    "ask_engineer",
    "run_developer",
    "run_reviewer",
    "add_follow_up",
    "mark_blocked",
    "mark_done",
]
ReviewerManagerAction = Literal[
    "complete_task",
    "run_developer",
    "add_follow_up_task",
    "refresh_artifacts",
    "split_task",
    "ask_user",
]
RoleRunStatus = Literal["completed", "blocked"]
RoleReturn = "TaskReturn | ValidationReturn | ReviewReturn"

VALID_TASK_TYPES: frozenset[str] = frozenset(get_args(TaskType))
VALID_STAGES: frozenset[str] = frozenset(get_args(Stage))
VALID_STATUSES: frozenset[str] = frozenset(get_args(Status))
VALID_SCALES: frozenset[str] = frozenset(get_args(Scale))
VALID_ARTIFACTS: frozenset[str] = frozenset(get_args(ArtifactName))
VALID_ROLES: frozenset[str] = frozenset(get_args(RoleName))

_TASK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ArtifactStatuses(BaseModel):
    """Approval status for the manager-owned planning artifacts.

    The copied manager workflow persists the design artifact under the
    historical key ``decision``. SpeCode V0 keeps that JSON shape and exposes a
    small ``design`` property for code that wants to use the product term.
    """

    model_config = ConfigDict(extra="forbid")

    task: Status = "in-progress"
    research: Status = "skipped"
    decision: Status = "skipped"
    tasks: Status = "skipped"

    @model_validator(mode="before")
    @classmethod
    def accept_design_alias(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "design" not in normalized:
            return normalized
        if "decision" in normalized and normalized["decision"] != normalized["design"]:
            raise ValueError("artifacts.design conflicts with artifacts.decision")
        normalized["decision"] = normalized.pop("design")
        return normalized

    @property
    def design(self) -> Status:
        return self.decision

    def status_for(self, artifact: ArtifactName) -> Status:
        return getattr(self, artifact)

    def stale(self) -> list[ArtifactName]:
        return [
            artifact
            for artifact in ("task", "research", "decision", "tasks")
            if self.status_for(artifact) == "stale"
        ]


class WorkflowState(BaseModel):
    """Durable task workflow state stored in ``tasks/<task-name>/state.json``."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    schema_version: Literal[1] = SCHEMA_VERSION
    task_name: str = Field(min_length=1)
    task_type: TaskType | None = None
    scale: Scale = "large"
    current_stage: Stage = "task"
    status: Status = "in-progress"
    artifacts: ArtifactStatuses = Field(default_factory=ArtifactStatuses)
    research_required: bool = False
    blocker: str | None = None
    pending_questions: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_task_name_slug(self) -> Self:
        if not _TASK_NAME_RE.fullmatch(self.task_name):
            raise ValueError(
                "task_name must be a simple slug without path separators"
            )
        return self

    @classmethod
    def new(cls, task_name: str, *, scale: Scale = "large") -> Self:
        return cls(task_name=task_name, scale=scale)

    @property
    def stale_artifacts(self) -> list[ArtifactName]:
        return self.artifacts.stale()

    def artifact_status(self, artifact: ArtifactName) -> Status:
        return self.artifacts.status_for(artifact)

    def planning_artifacts_ready(self) -> bool:
        return (
            self.status != "blocked"
            and self.artifacts.task == "approved"
            and self.artifacts.decision == "approved"
            and self.artifacts.tasks == "approved"
            and self.artifacts.research in {"approved", "skipped"}
            and not self.stale_artifacts
        )


class TaskReturn(BaseModel):
    """Validated developer role return.

    This is the structured form of the copied developer agent's
    ``Task Return`` block. The manager may use it as routing advice only after
    validation succeeds.
    """

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    result: TaskReturnResult
    files_changed: list[str] = Field(default_factory=list)
    checks_run: list[str] = Field(default_factory=list)
    interface_impact: InterfaceImpact = "none"
    contract_coverage: str = Field(min_length=1)
    suggested_split: str | None = None
    suggested_manager_action: DeveloperManagerAction
    blocker: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("suggested_split", "blocker", mode="before")
    @classmethod
    def normalize_none_text(cls, value: object) -> object:
        return _none_text_to_none(value)

    @model_validator(mode="after")
    def validate_routing_fields(self) -> Self:
        if self.result == "blocked" and self.blocker is None:
            raise ValueError("blocked developer returns must include a blocker")
        if self.result == "needs_split" and self.suggested_split is None:
            raise ValueError("needs_split developer returns must include suggested_split")
        if self.result == "ready_for_testing" and self.suggested_manager_action != "run_tester":
            raise ValueError("ready_for_testing developer returns must route to run_tester")
        return self


class ValidationReturn(BaseModel):
    """Validated tester role return."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    result: ValidationReturnResult
    tests_run: list[str] = Field(default_factory=list)
    contract_interface_coverage: str = Field(min_length=1)
    findings: list[str] = Field(default_factory=list)
    test_changes: list[str] = Field(default_factory=list)
    suggested_follow_up_task: str | None = None
    suggested_manager_action: TesterManagerAction
    blocker: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("suggested_follow_up_task", "blocker", mode="before")
    @classmethod
    def normalize_none_text(cls, value: object) -> object:
        return _none_text_to_none(value)

    @model_validator(mode="after")
    def validate_routing_fields(self) -> Self:
        if self.result == "blocked" and self.blocker is None:
            raise ValueError("blocked validation returns must include a blocker")
        if self.result == "fail" and not self.findings:
            raise ValueError("failed validation returns must include findings")
        if self.result == "fail" and self.suggested_manager_action not in {
            "run_developer",
            "ask_engineer",
            "mark_blocked",
        }:
            raise ValueError("failed validation must route to repair or a manager stop")
        if self.result == "pass" and self.suggested_manager_action not in {
            "run_reviewer",
            "mark_done",
        }:
            raise ValueError("passing validation must route to reviewer or done")
        return self


class ReviewReturn(BaseModel):
    """Validated reviewer role return."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    result: ReviewReturnResult
    findings: list[str] = Field(default_factory=list)
    interface_contract_findings: list[str] = Field(default_factory=list)
    scope_design_alignment: str = Field(min_length=1)
    risk_level: Scale
    suggested_manager_action: ReviewerManagerAction
    blocker: str | None = None
    notes: list[str] = Field(default_factory=list)

    @field_validator("blocker", mode="before")
    @classmethod
    def normalize_none_text(cls, value: object) -> object:
        return _none_text_to_none(value)

    @model_validator(mode="after")
    def validate_routing_fields(self) -> Self:
        if self.result == "blocked" and self.blocker is None:
            raise ValueError("blocked review returns must include a blocker")
        if self.result == "changes_requested" and not (
            self.findings or self.interface_contract_findings
        ):
            raise ValueError("changes_requested reviews must include findings")
        if self.result == "changes_requested" and self.suggested_manager_action not in {
            "run_developer",
            "refresh_artifacts",
            "split_task",
            "ask_user",
        }:
            raise ValueError("changes_requested reviews must route to repair or a manager stop")
        if self.result == "pass" and self.suggested_manager_action not in {
            "complete_task",
            "add_follow_up_task",
        }:
            raise ValueError("passing reviews must route to completion or follow-up")
        return self


class CommandRunSummary(BaseModel):
    """Compact command result summary for role and run records."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["command"] = "command"
    command: str = Field(min_length=1)
    status: str = Field(min_length=1)
    exit_code: int | None = None
    purpose: str | None = None
    blocker: str | None = None


class FileOperationSummary(BaseModel):
    """Compact file operation summary for role and run records."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["file"] = "file"
    operation: str = Field(min_length=1)
    path: str = Field(min_length=1)
    status: str = Field(min_length=1)
    action: str | None = None
    changed: bool | None = None
    blocker: str | None = None


class WebSearchSummary(BaseModel):
    """Compact web search summary for role and run records."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["web_search"] = "web_search"
    query: str = Field(min_length=1)
    status: str = Field(min_length=1)
    result_count: int = Field(default=0, ge=0)
    sources: list[str] = Field(default_factory=list)
    backend: str | None = None
    blocker: str | None = None


class RoleRunRequest(BaseModel):
    """One deterministic role execution request."""

    model_config = ConfigDict(extra="forbid")

    task_name: str = Field(min_length=1)
    role: RoleName
    task: str = Field(min_length=1)
    instructions: str = ""
    approved_scope: bool = True
    automation_policy: AutomationPolicy = "approved"
    previous_run_ids: list[str] = Field(default_factory=list)
    artifact_paths: dict[str, str] = Field(default_factory=dict)
    command_summaries: list[CommandRunSummary] = Field(default_factory=list)
    file_summaries: list[FileOperationSummary] = Field(default_factory=list)
    web_summaries: list[WebSearchSummary] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_task_name_slug(self) -> Self:
        if not _TASK_NAME_RE.fullmatch(self.task_name):
            raise ValueError(
                "task_name must be a simple slug without path separators"
            )
        return self


class RoleRunResult(BaseModel):
    """Validated result returned by an AgentRuntime."""

    model_config = ConfigDict(extra="forbid")

    task_name: str = Field(min_length=1)
    role: RoleName
    status: RoleRunStatus = "completed"
    role_return: TaskReturn | ValidationReturn | ReviewReturn
    command_summaries: list[CommandRunSummary] = Field(default_factory=list)
    file_summaries: list[FileOperationSummary] = Field(default_factory=list)
    web_summaries: list[WebSearchSummary] = Field(default_factory=list)
    blocker: str | None = None

    @field_validator("blocker", mode="before")
    @classmethod
    def normalize_none_text(cls, value: object) -> object:
        return _none_text_to_none(value)

    @model_validator(mode="after")
    def validate_role_return_matches_role(self) -> Self:
        expected_types: dict[RoleName, type[BaseModel]] = {
            "developer": TaskReturn,
            "tester": ValidationReturn,
            "reviewer": ReviewReturn,
        }
        if not isinstance(self.role_return, expected_types[self.role]):
            raise ValueError(f"{self.role} result has the wrong role return model")
        if self.status == "blocked" and self.blocker is None:
            self.blocker = getattr(self.role_return, "blocker", None)
        if self.status == "blocked" and self.blocker is None:
            raise ValueError("blocked role run results must include a blocker")
        return self


def parse_role_return(role: RoleName, payload: object) -> TaskReturn | ValidationReturn | ReviewReturn:
    """Validate an untrusted role payload for the expected role."""

    model_by_role: dict[RoleName, type[TaskReturn] | type[ValidationReturn] | type[ReviewReturn]] = {
        "developer": TaskReturn,
        "tester": ValidationReturn,
        "reviewer": ReviewReturn,
    }
    return model_by_role[role].model_validate(payload)


def _none_text_to_none(value: object) -> object:
    if isinstance(value, str) and value.strip().lower() == "none":
        return None
    return value
