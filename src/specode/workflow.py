"""Deterministic SpeCode workflow transitions for the V0 SDD spine."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from specode.artifacts import ArtifactStore
from specode.run_store import RunRecord, RunStore
from specode.runtime import AgentRuntime, FakeAgentRuntime
from specode.schemas import (
    ArtifactName,
    ArtifactStatuses,
    AutomationPolicy,
    CommandRunSummary,
    FileOperationSummary,
    ReviewReturn,
    RoleName,
    RoleRunRequest,
    Stage,
    Status,
    TaskReturn,
    TaskType,
    ValidationReturn,
    WebSearchSummary,
    WorkflowState,
)


ClassificationStatus = Literal["classified", "ambiguous"]
RequirementsShape = Literal["task-requirements", "bugfix-spec"]


@dataclass(frozen=True)
class TaskClassification:
    """Deterministic feature-vs-bugfix classification result."""

    status: ClassificationStatus
    task_type: TaskType | None
    requirements_shape: RequirementsShape | None
    research_required: bool
    reason: str
    question: str | None = None

    @property
    def is_clear(self) -> bool:
        return self.status == "classified" and self.task_type is not None


@dataclass(frozen=True)
class WorkflowTransition:
    """Observable result of one workflow event."""

    events: tuple[str, ...]
    state: WorkflowState
    next_stage: Stage
    message: str
    recommended_next_step: str
    classification: TaskClassification | None = None
    created: bool = False
    resumed: bool = False

    @property
    def blocked(self) -> bool:
        return self.state.status == "blocked"


@dataclass(frozen=True)
class RolePipelineResult:
    """Observable result of one developer/tester/reviewer pipeline run."""

    events: tuple[str, ...]
    state: WorkflowState
    run_records: tuple[RunRecord, ...]
    message: str
    recommended_next_step: str

    @property
    def blocked(self) -> bool:
        return self.state.status == "blocked"

    @property
    def done(self) -> bool:
        return self.state.status == "done"


@dataclass(frozen=True)
class RepairStopConditions:
    """Deterministic manager-owned stop conditions for repair routing."""

    changed_scope: bool = False
    stale_artifacts: bool = False
    design_update: bool = False
    task_split: bool = False
    destructive_action: bool = False
    new_approval: bool = False
    credentials: bool = False
    unsafe_command_policy: bool = False
    unresolved_blocker: str | None = None


class WorkflowEngine:
    """Own deterministic state routing for SpeCode's V0 workflow spine."""

    _BUGFIX_START_RE = re.compile(r"^\s*(fix|repair|debug|resolve|correct)\b", re.I)
    _FEATURE_START_RE = re.compile(r"^\s*(add|build|create|implement|support|enable)\b", re.I)
    _BUGFIX_RE = re.compile(
        r"\b("
        r"bug|bugfix|broken|crash|defect|error|fail(?:ing|s|ed)?|fix|flaky|"
        r"incorrect|regression|repair|resolve|wrong"
        r")\b",
        re.I,
    )
    _FEATURE_RE = re.compile(
        r"\b("
        r"add|allow|build|create|enable|feature|implement|integrate|new|support"
        r")\b",
        re.I,
    )
    _RESEARCH_RE = re.compile(
        r"\b("
        r"api|architecture|auth|concurrency|current behavior|data|external|"
        r"integration|migration|operations|performance|privacy|regression|"
        r"root cause|security"
        r")\b",
        re.I,
    )
    _ARTIFACT_FILENAMES: dict[ArtifactName, str] = {
        "task": "task.md",
        "research": "context.md",
        "decision": "design.md",
        "tasks": "tasks.md",
    }
    _STAGE_ARTIFACTS: dict[Stage, ArtifactName] = {
        "task": "task",
        "research": "research",
        "decision": "decision",
        "tasks": "tasks",
    }
    _GATE_BLOCKER_PREFIX = "Implementation blocked:"
    _MAX_REPAIR_PASSES = 10
    _GENERIC_SOURCE_FILENAMES = frozenset(
        {"request", "requirements", "spec", "task", "tasks"}
    )

    def __init__(self, store: ArtifactStore) -> None:
        self.store = store

    def start(
        self,
        task_name: str,
        request_text: str,
        *,
        research_required: bool | None = None,
    ) -> WorkflowTransition:
        """Create a new workflow state or resume the existing task state."""

        if self.store.task_paths(task_name).state.exists():
            return self.resume(task_name)

        classification = self.classify(request_text)
        if not classification.is_clear:
            state = WorkflowState.new(task_name)
            state.status = "blocked"
            state.blocker = "Resolve whether this /spec request is a feature or bugfix."
            if classification.question is not None:
                state.pending_questions.append(classification.question)
            self.store.save_task_state(state)
            return self._transition(
                state,
                ("new", "classification:ambiguous", "blocked", "status"),
                classification=classification,
                created=True,
            )

        needs_research = (
            classification.research_required
            if research_required is None
            else research_required
        )
        state = WorkflowState(
            task_name=task_name,
            task_type=classification.task_type,
            status="pending-approval",
            artifacts=ArtifactStatuses(
                task="pending-approval",
                research="in-progress" if needs_research else "skipped",
                decision="skipped",
                tasks="skipped",
            ),
            research_required=needs_research,
            notes=[
                (
                    f"Classified as {classification.task_type}; use "
                    f"{classification.requirements_shape} for task.md."
                )
            ],
        )
        self.store.save_task_state(state)
        research_event = "research:inserted" if needs_research else "research:skipped"
        return self._transition(
            state,
            ("new", f"classification:{classification.task_type}", research_event, "status"),
            classification=classification,
            created=True,
        )

    def resume(self, task_name: str) -> WorkflowTransition:
        """Load an existing state and report the next deterministic stage."""

        state = self.store.load_task_state(task_name)
        return self._transition(state, ("resume", "status"), resumed=True)

    def status(self, task_name: str) -> WorkflowTransition:
        """Synchronize persisted state with the next required V0 stage."""

        state = self.store.load_task_state(task_name)
        return self._transition(state, ("status",))

    def latest_task_name(self) -> str | None:
        """Return the latest persisted task known to the workflow store."""

        return self.store.latest_task_name()

    def status_latest(self) -> WorkflowTransition | None:
        """Synchronize the latest task state, if any exists."""

        task_name = self.latest_task_name()
        if task_name is None:
            return None
        return self.status(task_name)

    def approve_latest(self) -> WorkflowTransition | None:
        """Approve the latest task gate, if any task exists."""

        task_name = self.latest_task_name()
        if task_name is None:
            return None
        return self.approve(task_name)

    def revise_latest(self, instruction: str) -> WorkflowTransition | None:
        """Record a revision on the latest task, if any task exists."""

        task_name = self.latest_task_name()
        if task_name is None:
            return None
        return self.revise(task_name, instruction)

    def cancel_latest(self, reason: str | None = None) -> WorkflowTransition | None:
        """Cancel the latest task, if any task exists."""

        task_name = self.latest_task_name()
        if task_name is None:
            return None
        return self.cancel(task_name, reason)

    def record_source_drift(
        self,
        task_name: str,
        *,
        source_path: str,
        imported_hash: str,
        current_hash: str,
    ) -> WorkflowTransition:
        """Mark imported task intent stale when its source file changed."""

        state = self.store.load_task_state(task_name)
        state.current_stage = "task"
        state.artifacts.task = "stale"
        state.status = "blocked"
        state.blocker = (
            "Source task file changed since import: "
            f"{source_path} (imported {imported_hash[:12]}, current {current_hash[:12]})."
        )
        state.notes.append(state.blocker)
        return self._transition(
            state,
            ("resume", "source-file:drift", "artifact:task:stale", "blocked", "status"),
            resumed=True,
        )

    def approve(self, task_name: str) -> WorkflowTransition:
        """Approve the current planning artifact or implementation gate."""

        state = self.store.load_task_state(task_name)
        if state.status == "blocked" and not self._is_recoverable_gate_blocker(state):
            return self._transition(state, ("approve", "blocked", "status"))

        artifact = self._STAGE_ARTIFACTS.get(state.current_stage)
        if artifact is not None:
            missing_blocker = self._missing_artifact_blocker(state, artifact)
            if missing_blocker is not None:
                self._block(state, missing_blocker)
                return self._transition(
                    state,
                    ("approve", f"artifact:{artifact}", "blocker:missing-artifact", "status"),
                )

            if state.artifact_status(artifact) == "stale":
                self._block(
                    state,
                    (
                        "Implementation blocked: "
                        f"{self._ARTIFACT_FILENAMES[artifact]} is stale and must be revised."
                    ),
                )
                return self._transition(
                    state,
                    ("approve", f"artifact:{artifact}", "blocker:stale-artifact", "status"),
                )

            setattr(state.artifacts, artifact, "approved")
            state.status = "approved"
            state.blocker = None
            return self._transition(
                state,
                ("approve", f"artifact:{artifact}:approved", "status"),
            )

        if state.current_stage == "implementation":
            gate_artifact, gate_blocker = self._implementation_gate_issue(state)
            if gate_blocker is not None:
                if gate_artifact is not None:
                    state.current_stage = self._stage_for_artifact(gate_artifact)
                self._block(state, gate_blocker)
                return self._transition(
                    state,
                    ("approve", "implementation-gate", "blocked", "status"),
                )

            state.status = "approved"
            state.blocker = None
            return self._transition(
                state,
                ("approve", "implementation:approved", "status"),
            )

        return self._transition(state, ("approve", "status"))

    def revise(self, task_name: str, instruction: str) -> WorkflowTransition:
        """Record a requested revision without editing artifacts."""

        state = self.store.load_task_state(task_name)
        note = instruction.strip() or "Revision requested."
        artifact = self._STAGE_ARTIFACTS.get(state.current_stage)

        if artifact is not None:
            setattr(state.artifacts, artifact, "in-progress")
            state.status = "in-progress"
            state.blocker = None
            state.notes.append(
                f"Revision requested for {self._ARTIFACT_FILENAMES[artifact]}: {note}"
            )
            return self._transition(
                state,
                ("revise", f"artifact:{artifact}:in-progress", "status"),
            )

        if state.current_stage == "implementation":
            state.current_stage = "tasks"
            state.artifacts.tasks = "stale"
            state.status = "stale"
            state.blocker = None
            state.notes.append(f"Implementation scope revision requested: {note}")
            return self._transition(
                state,
                ("revise", "implementation-scope", "artifact:tasks:stale", "status"),
            )

        state.notes.append(f"Revision requested: {note}")
        return self._transition(state, ("revise", "status"))

    def cancel(self, task_name: str, reason: str | None = None) -> WorkflowTransition:
        """Stop the active task deterministically without deleting artifacts."""

        state = self.store.load_task_state(task_name)
        detail = reason.strip() if reason else "No reason provided."
        state.status = "blocked"
        state.blocker = f"Task canceled: {detail}"
        state.notes.append(state.blocker)
        return self._transition(state, ("cancel", "blocked", "status"))

    def check_implementation_gate(self, task_name: str) -> WorkflowTransition:
        """Require approved, present, fresh planning artifacts before coding."""

        state = self.store.load_task_state(task_name)
        gate_artifact, gate_blocker = self._implementation_gate_issue(state)
        if gate_blocker is not None:
            if gate_artifact is not None:
                state.current_stage = self._stage_for_artifact(gate_artifact)
            self._block(state, gate_blocker)
            return self._transition(
                state,
                ("implementation-gate", "blocked", "status"),
            )

        state.current_stage = "implementation"
        if state.status != "approved":
            state.status = "pending-approval"
        state.blocker = None
        return self._transition(
            state,
            ("implementation-gate", "ready", "status"),
        )

    def assess_repair(
        self,
        task_name: str,
        stop_conditions: RepairStopConditions | None = None,
    ) -> WorkflowTransition:
        """Route an approved-scope repair or stop when manager gates require it."""

        state = self.store.load_task_state(task_name)
        conditions = stop_conditions or RepairStopConditions()
        blocker = self._repair_blocker(conditions)

        if blocker is not None:
            state.current_stage = "implementation"
            self._block(state, blocker)
            return self._transition(
                state,
                ("repair", "blocked", "status"),
            )

        gate_artifact, gate_blocker = self._implementation_gate_issue(state)
        if gate_blocker is not None:
            if gate_artifact is not None:
                state.current_stage = self._stage_for_artifact(gate_artifact)
            self._block(state, gate_blocker)
            return self._transition(
                state,
                ("repair", "implementation-gate", "blocked", "status"),
            )

        state.current_stage = "implementation"
        state.status = "approved"
        state.blocker = None
        return self._transition(
            state,
            ("repair", "approved-scope", "route:developer", "status"),
        )

    def run_role_pipeline(
        self,
        task_name: str,
        *,
        runtime: AgentRuntime | None = None,
        run_store: RunStore | None = None,
        automation_policy: AutomationPolicy = "approved",
        command_summaries: tuple[CommandRunSummary, ...] = (),
        file_summaries: tuple[FileOperationSummary, ...] = (),
        web_summaries: tuple[WebSearchSummary, ...] = (),
        max_repair_passes: int = _MAX_REPAIR_PASSES,
    ) -> RolePipelineResult:
        """Run developer -> tester -> reviewer with manager-owned repair routing."""

        runtime = runtime or FakeAgentRuntime()
        run_store = run_store or RunStore(self.store)
        state = self.store.load_task_state(task_name)
        records: list[RunRecord] = []
        events: list[str] = ["pipeline:start"]
        repair_passes = 0
        next_role: RoleName = "developer"

        gate_blocker = self._pipeline_start_blocker(state)
        if gate_blocker is not None:
            self._block(state, gate_blocker)
            self.store.save_task_state(state)
            return self._pipeline_result(
                state,
                records,
                (*events, "blocked", "status"),
            )

        while True:
            self._refresh_external_stop_signals(state)
            gate_artifact, gate_blocker = self._implementation_gate_issue(state)
            if gate_blocker is not None:
                if gate_artifact is not None:
                    state.current_stage = self._stage_for_artifact(gate_artifact)
                self._block(state, gate_blocker)
                self.store.save_task_state(state)
                return self._pipeline_result(
                    state,
                    records,
                    (*events, "implementation-gate", "blocked", "status"),
                )

            result = runtime.run_role(
                self._role_request(
                    state,
                    next_role,
                    previous_run_ids=[record.run_id for record in records],
                    automation_policy=automation_policy,
                    command_summaries=command_summaries,
                    file_summaries=file_summaries,
                    web_summaries=web_summaries,
                )
            )
            record = run_store.write_result(result)
            records.append(record)
            events.append(f"run:{next_role}:{record.status}")
            state.notes.append(f"{next_role} run recorded as {record.run_id}.")
            self._refresh_external_stop_signals(state)

            role_return = result.role_return
            if result.status == "blocked" or role_return.result == "blocked":
                self._block_role(state, next_role, getattr(role_return, "blocker", None))
                self.store.save_task_state(state)
                return self._pipeline_result(state, records, (*events, "blocked", "status"))

            if next_role == "developer":
                developer_return = self._as_developer_return(role_return)
                if developer_return.result == "needs_split":
                    self._block(
                        state,
                        "Repair blocked: task split. "
                        f"{developer_return.suggested_split or 'Split required.'}",
                    )
                    self.store.save_task_state(state)
                    return self._pipeline_result(state, records, (*events, "blocked", "status"))
                state.current_stage = "testing"
                state.status = "approved"
                next_role = "tester"
                continue

            if next_role == "tester":
                tester_return = self._as_validation_return(role_return)
                if tester_return.result == "fail":
                    repair_passes += 1
                    repair_blocker = self._pipeline_repair_blocker(
                        repair_passes,
                        max_repair_passes,
                        tester_return.suggested_manager_action,
                    )
                    if repair_blocker is not None:
                        state.current_stage = "implementation"
                        self._block(state, repair_blocker)
                        self.store.save_task_state(state)
                        return self._pipeline_result(
                            state,
                            records,
                            (*events, "repair:blocked", "status"),
                        )
                    state.current_stage = "implementation"
                    state.status = "approved"
                    state.blocker = None
                    events.append("repair:tester-fail:route:developer")
                    next_role = "developer"
                    continue
                state.current_stage = "review"
                state.status = "approved"
                next_role = "reviewer"
                continue

            reviewer_return = self._as_review_return(role_return)
            if reviewer_return.result == "changes_requested":
                repair_passes += 1
                repair_blocker = self._review_repair_blocker(
                    repair_passes,
                    max_repair_passes,
                    reviewer_return.suggested_manager_action,
                )
                if repair_blocker is not None:
                    state.current_stage = "review"
                    self._block(state, repair_blocker)
                    self.store.save_task_state(state)
                    return self._pipeline_result(
                        state,
                        records,
                        (*events, "repair:blocked", "status"),
                    )
                state.current_stage = "implementation"
                state.status = "approved"
                state.blocker = None
                events.append("repair:reviewer-changes:route:developer")
                next_role = "developer"
                continue

            state.current_stage = "done"
            state.status = "done"
            state.blocker = None
            state.notes.append("Role pipeline completed with reviewer pass.")
            self.store.save_task_state(state)
            return self._pipeline_result(state, records, (*events, "done", "status"))

    def classify(self, request_text: str) -> TaskClassification:
        """Classify a /spec request without model calls or repository mutation."""

        bugfix_hit = bool(self._BUGFIX_RE.search(request_text))
        feature_hit = bool(self._FEATURE_RE.search(request_text))
        bugfix_start = bool(self._BUGFIX_START_RE.search(request_text))
        feature_start = bool(self._FEATURE_START_RE.search(request_text))

        if bugfix_hit and (not feature_hit or bugfix_start):
            return TaskClassification(
                status="classified",
                task_type="bugfix",
                requirements_shape="bugfix-spec",
                research_required=self._needs_research(request_text, "bugfix"),
                reason="The request describes broken, failing, or incorrect existing behavior.",
            )

        if feature_hit and (not bugfix_hit or feature_start):
            return TaskClassification(
                status="classified",
                task_type="feature",
                requirements_shape="task-requirements",
                research_required=self._needs_research(request_text, "feature"),
                reason="The request asks SpeCode to add or create a capability.",
            )

        return TaskClassification(
            status="ambiguous",
            task_type=None,
            requirements_shape=None,
            research_required=False,
            reason="The request does not clearly choose the feature or bugfix spec shape.",
            question=(
                "Is this /spec request a new feature or a bugfix for existing behavior?"
            ),
        )

    def _role_request(
        self,
        state: WorkflowState,
        role: RoleName,
        *,
        previous_run_ids: list[str],
        automation_policy: AutomationPolicy,
        command_summaries: tuple[CommandRunSummary, ...],
        file_summaries: tuple[FileOperationSummary, ...],
        web_summaries: tuple[WebSearchSummary, ...],
    ) -> RoleRunRequest:
        task_text = self.store.task_paths(state.task_name).task.read_text(encoding="utf-8")
        return RoleRunRequest(
            task_name=state.task_name,
            role=role,
            task=task_text,
            instructions=(
                f"Run the {role} role with workspace-scoped tool access under "
                f"{automation_policy} automation policy. Manager owns gates "
                "and routing decisions."
            ),
            approved_scope=True,
            automation_policy=automation_policy,
            previous_run_ids=previous_run_ids,
            artifact_paths=self._role_artifact_paths(state),
            command_summaries=list(command_summaries),
            file_summaries=list(file_summaries),
            web_summaries=list(web_summaries),
        )

    def _role_artifact_paths(self, state: WorkflowState) -> dict[str, str]:
        paths: dict[str, str] = {}
        for artifact, filename in self._ARTIFACT_FILENAMES.items():
            path = self.store.task_artifact_path(state.task_name, filename)
            if path.exists():
                paths[artifact] = path.as_posix()
        return paths

    def _pipeline_start_blocker(self, state: WorkflowState) -> str | None:
        if state.status == "blocked" and not self._is_recoverable_gate_blocker(state):
            return state.blocker or "Pipeline blocked: unresolved blocker."
        if state.current_stage != "implementation" or state.status != "approved":
            return "Implementation blocked: implementation scope is not approved."
        return None

    def _refresh_external_stop_signals(self, state: WorkflowState) -> None:
        persisted = self.store.load_task_state(state.task_name)
        for artifact in self._ARTIFACT_FILENAMES:
            if persisted.artifact_status(artifact) == "stale":
                setattr(state.artifacts, artifact, "stale")
        if persisted.status == "blocked" and not self._is_recoverable_gate_blocker(persisted):
            state.status = "blocked"
            state.blocker = persisted.blocker
            state.current_stage = persisted.current_stage

    def _pipeline_repair_blocker(
        self,
        repair_passes: int,
        max_repair_passes: int,
        suggested_action: str,
    ) -> str | None:
        if repair_passes > max_repair_passes:
            return "Repair blocked: maximum repair passes exceeded."
        if suggested_action in {"ask_engineer", "mark_blocked"}:
            return "Repair blocked: tester requested manager intervention."
        return None

    def _review_repair_blocker(
        self,
        repair_passes: int,
        max_repair_passes: int,
        suggested_action: str,
    ) -> str | None:
        if repair_passes > max_repair_passes:
            return "Repair blocked: maximum repair passes exceeded."
        if suggested_action == "refresh_artifacts":
            return "Repair blocked: design update."
        if suggested_action == "split_task":
            return "Repair blocked: task split."
        if suggested_action == "ask_user":
            return "Repair blocked: new approval."
        return None

    def _block_role(
        self,
        state: WorkflowState,
        role: RoleName,
        blocker: str | None,
    ) -> None:
        state.current_stage = {
            "developer": "implementation",
            "tester": "testing",
            "reviewer": "review",
        }[role]
        label = {
            "developer": "Developer",
            "tester": "Tester",
            "reviewer": "Reviewer",
        }[role]
        self._block(state, f"{label} blocked: {blocker or 'unresolved blocker'}")

    def _pipeline_result(
        self,
        state: WorkflowState,
        records: list[RunRecord],
        events: tuple[str, ...],
    ) -> RolePipelineResult:
        _next_stage, message, recommended = self._route_state(state)
        self.store.save_task_state(state)
        return RolePipelineResult(
            events=events,
            state=state,
            run_records=tuple(records),
            message=message,
            recommended_next_step=recommended,
        )

    def _as_developer_return(self, role_return: object) -> TaskReturn:
        if not isinstance(role_return, TaskReturn):
            raise TypeError("developer runtime returned the wrong role model")
        return role_return

    def _as_validation_return(self, role_return: object) -> ValidationReturn:
        if not isinstance(role_return, ValidationReturn):
            raise TypeError("tester runtime returned the wrong role model")
        return role_return

    def _as_review_return(self, role_return: object) -> ReviewReturn:
        if not isinstance(role_return, ReviewReturn):
            raise TypeError("reviewer runtime returned the wrong role model")
        return role_return

    def _needs_research(self, request_text: str, task_type: TaskType) -> bool:
        if self._RESEARCH_RE.search(request_text):
            return True
        return task_type == "bugfix" and not re.search(
            r"\b(copy|label|text|typo)\b",
            request_text,
            re.I,
        )

    def derive_task_slug(self, request_text: str) -> str:
        """Derive a deterministic task slug from typed /spec intent."""

        return _slugify(_representative_text(request_text), fallback="spec-task")

    def derive_file_task_slug(self, source_path: Path, source_text: str) -> str:
        """Derive a deterministic task slug from a source task file path."""

        stem = source_path.stem
        if stem.lower() in self._GENERIC_SOURCE_FILENAMES:
            parent_name = source_path.parent.name
            if parent_name:
                stem = parent_name
        return _slugify(stem or _representative_text(source_text), fallback="spec-task")

    def _transition(
        self,
        state: WorkflowState,
        events: tuple[str, ...],
        *,
        classification: TaskClassification | None = None,
        created: bool = False,
        resumed: bool = False,
    ) -> WorkflowTransition:
        next_stage, message, recommended = self._route_state(state)
        self.store.save_task_state(state)
        return WorkflowTransition(
            events=events,
            state=state,
            next_stage=next_stage,
            message=message,
            recommended_next_step=recommended,
            classification=classification,
            created=created,
            resumed=resumed,
        )

    def _route_state(self, state: WorkflowState) -> tuple[Stage, str, str]:
        if state.current_stage == "done" or state.status == "done":
            state.current_stage = "done"
            state.status = "done"
            return (
                "done",
                "Role pipeline completed successfully.",
                "Task is complete.",
            )

        if state.status == "blocked":
            return (
                state.current_stage,
                f"Workflow is blocked: {state.blocker or 'unresolved blocker'}",
                self._blocked_recommendation(state),
            )

        if state.artifacts.task != "approved":
            state.current_stage = "task"
            state.status = self._required_stage_status(state.artifacts.task)
            return (
                "task",
                "Task requirements are the next required artifact.",
                "Create or approve task.md before design, tasks, or implementation.",
            )

        if state.research_required and state.artifacts.research != "approved":
            state.current_stage = "research"
            if state.artifacts.research == "skipped":
                state.artifacts.research = "in-progress"
            state.status = self._required_stage_status(state.artifacts.research)
            return (
                "research",
                "Research is inserted before design because evidence is needed.",
                "Create or approve context.md before design.",
            )

        if state.artifacts.decision != "approved":
            state.current_stage = "decision"
            if state.artifacts.decision == "skipped":
                state.artifacts.decision = "in-progress"
            state.status = self._required_stage_status(state.artifacts.decision)
            return (
                "decision",
                "V0 requires design.md before implementation tasks.",
                "Create or approve design.md before tasks.md.",
            )

        if state.artifacts.tasks != "approved":
            state.current_stage = "tasks"
            if state.artifacts.tasks == "skipped":
                state.artifacts.tasks = "in-progress"
            state.status = self._required_stage_status(state.artifacts.tasks)
            return (
                "tasks",
                "V0 requires tasks.md before implementation.",
                "Create or approve tasks.md before implementation.",
            )

        if state.current_stage == "implementation" and state.status == "approved":
            return (
                "implementation",
                "Implementation scope is approved.",
                "Run developer -> tester -> reviewer sequentially unless a stop condition appears.",
            )

        state.current_stage = "implementation"
        state.status = "pending-approval"
        return (
            "implementation",
            "Planning artifacts are approved; implementation is the next stage.",
            "Approve implementation scope before developer work starts.",
        )

    def _required_stage_status(self, artifact_status: Status) -> Status:
        if artifact_status in {"blocked", "in-progress", "pending-approval", "stale"}:
            return artifact_status
        return "in-progress"

    def _required_artifacts(self, state: WorkflowState) -> tuple[ArtifactName, ...]:
        artifacts: list[ArtifactName] = ["task", "decision", "tasks"]
        if state.research_required:
            artifacts.insert(1, "research")
        return tuple(artifacts)

    def _implementation_gate_issue(
        self,
        state: WorkflowState,
    ) -> tuple[ArtifactName | None, str | None]:
        if state.status == "blocked" and not self._is_recoverable_gate_blocker(state):
            return None, state.blocker or "Implementation blocked: unresolved blocker."

        for artifact in self._required_artifacts(state):
            status = state.artifact_status(artifact)
            filename = self._ARTIFACT_FILENAMES[artifact]
            if status == "stale":
                return artifact, f"Implementation blocked: {filename} is stale and must be revised."
            if status != "approved":
                return artifact, f"Implementation blocked: {filename} is {status}, not approved."
            missing_blocker = self._missing_artifact_blocker(state, artifact)
            if missing_blocker is not None:
                return artifact, missing_blocker
        return None, None

    def _missing_artifact_blocker(
        self,
        state: WorkflowState,
        artifact: ArtifactName,
    ) -> str | None:
        path = self.store.task_artifact_path(
            state.task_name,
            self._ARTIFACT_FILENAMES[artifact],
        )
        if path.exists():
            return None
        return (
            "Implementation blocked: "
            f"{self._ARTIFACT_FILENAMES[artifact]} is missing."
        )

    def _repair_blocker(self, conditions: RepairStopConditions) -> str | None:
        if conditions.unresolved_blocker:
            return f"Repair blocked: {conditions.unresolved_blocker}"

        stops: list[str] = []
        if conditions.changed_scope:
            stops.append("changed scope")
        if conditions.stale_artifacts:
            stops.append("stale artifacts")
        if conditions.design_update:
            stops.append("design update")
        if conditions.task_split:
            stops.append("task split")
        if conditions.destructive_action:
            stops.append("destructive action")
        if conditions.new_approval:
            stops.append("new approval")
        if conditions.credentials:
            stops.append("required credentials")
        if conditions.unsafe_command_policy:
            stops.append("unsafe command policy")

        if not stops:
            return None
        return "Repair blocked: " + ", ".join(stops) + "."

    def _block(self, state: WorkflowState, blocker: str) -> None:
        state.status = "blocked"
        state.blocker = blocker

    def _is_recoverable_gate_blocker(self, state: WorkflowState) -> bool:
        return bool(state.blocker and state.blocker.startswith(self._GATE_BLOCKER_PREFIX))

    def _blocked_recommendation(self, state: WorkflowState) -> str:
        blocker = state.blocker or ""
        if blocker.startswith("Task canceled:"):
            return "Start or resume another /spec task when ready."
        if blocker.startswith(self._GATE_BLOCKER_PREFIX):
            return "Revise or restore the required planning artifact, then run the implementation gate again."
        if blocker.startswith("Repair blocked:"):
            return "Return to the manager gate for an explicit decision before repair continues."
        if state.pending_questions:
            return "Answer the high-importance clarification question before planning continues."
        return "Resolve the blocker before workflow continues."

    def _stage_for_artifact(self, artifact: ArtifactName) -> Stage:
        if artifact == "task":
            return "task"
        if artifact == "research":
            return "research"
        if artifact == "decision":
            return "decision"
        return "tasks"


def _representative_text(text: str) -> str:
    stripped = text.strip()
    for line in stripped.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.startswith("#"):
            candidate = candidate.lstrip("#").strip()
        return candidate
    return stripped


def _slugify(text: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        return fallback
    parts = slug.split("-")
    return "-".join(parts[:8])
