"""Compact run record persistence for role pipeline executions."""

from __future__ import annotations

import shlex
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from specode.artifacts import ArtifactStore
from specode.schemas import (
    CommandRunSummary,
    FileOperationSummary,
    RoleName,
    RoleRunResult,
    WebSearchSummary,
)


RUN_RECORD_SCHEMA_VERSION = 1


class RunRecord(BaseModel):
    """A compact durable record under ``tasks/<task>/runs/<run-id>.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = RUN_RECORD_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    task_name: str = Field(min_length=1)
    role: RoleName
    status: str = Field(min_length=1)
    created_at: str = Field(min_length=1)
    role_return: dict[str, Any]
    commands: list[CommandRunSummary] = Field(default_factory=list)
    files: list[FileOperationSummary] = Field(default_factory=list)
    web_searches: list[WebSearchSummary] = Field(default_factory=list)
    blocker: str | None = None
    notes: list[str] = Field(default_factory=list)


class RunStore:
    """Persist and read role run records through ArtifactStore."""

    def __init__(
        self,
        store: ArtifactStore | Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store if isinstance(store, ArtifactStore) else ArtifactStore(store)
        self._clock = clock or (lambda: datetime.now(UTC))

    def write_result(
        self,
        result: RoleRunResult,
        *,
        run_id: str | None = None,
    ) -> RunRecord:
        run_id = run_id or self.next_run_id(result.task_name, result.role)
        record = RunRecord(
            run_id=run_id,
            task_name=result.task_name,
            role=result.role,
            status=result.status,
            created_at=_timestamp(self._clock()),
            role_return=result.role_return.model_dump(
                mode="json",
                exclude_none=True,
            ),
            commands=result.command_summaries,
            files=result.file_summaries,
            web_searches=result.web_summaries,
            blocker=result.blocker,
            notes=list(getattr(result.role_return, "notes", [])),
        )
        self.store.ensure_runs_dir(record.task_name)
        self.store.write_json(
            self.store.run_path(record.task_name, record.run_id),
            record.model_dump(
                mode="json",
                exclude_none=True,
                exclude_defaults=True,
            ),
        )
        return record

    def read_run(self, task_name: str, run_id: str) -> RunRecord:
        return RunRecord.model_validate(
            self.store.read_json(self.store.run_path(task_name, run_id))
        )

    def list_runs(self, task_name: str) -> tuple[RunRecord, ...]:
        runs_dir = self.store.task_paths(task_name).runs
        if not runs_dir.exists():
            return ()
        records = [
            self.read_run(task_name, path.stem)
            for path in sorted(runs_dir.glob("*.json"))
        ]
        return tuple(records)

    def next_run_id(self, task_name: str, role: RoleName) -> str:
        existing = self.list_runs(task_name)
        return f"{len(existing) + 1:04d}-{role}"


def summarize_command_result(result: Any) -> CommandRunSummary:
    """Return a compact command summary without stdout, stderr, or env values."""

    blocker = getattr(result, "blocker", None)
    policy = getattr(result, "policy", None)
    if blocker is None and policy is not None:
        blocker = getattr(policy, "blocker_reason", None)

    return CommandRunSummary(
        command=shlex.join(tuple(getattr(result, "command"))),
        status=str(getattr(result, "status")),
        exit_code=getattr(result, "exit_code", None),
        purpose=getattr(result, "purpose", None),
        blocker=blocker,
    )


def summarize_file_operation(result: Any) -> FileOperationSummary:
    """Return a compact file tool summary without file content."""

    summary = getattr(result, "summary", None)
    action = getattr(summary, "action", None)
    changed = getattr(summary, "changed", None)
    return FileOperationSummary(
        operation=str(getattr(result, "operation")),
        path=str(getattr(result, "path")),
        status=str(getattr(result, "status")),
        action=action,
        changed=changed,
        blocker=getattr(result, "blocker", None),
    )


def summarize_web_search(result: Any) -> WebSearchSummary:
    """Return a compact web search summary without raw snippets or pages."""

    sources = getattr(result, "sources", None)
    if sources is None:
        sources = getattr(result, "urls", None)
    if sources is None:
        sources = []

    result_count = getattr(result, "result_count", None)
    if result_count is None:
        result_count = len(sources)

    return WebSearchSummary(
        query=str(getattr(result, "query")),
        status=str(getattr(result, "status")),
        result_count=result_count,
        sources=[str(source) for source in sources],
        backend=getattr(result, "backend", None),
        blocker=getattr(result, "blocker", None),
    )


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
