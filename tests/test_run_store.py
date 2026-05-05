from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from specode.execution import CommandRequest, LocalExecutionBackend
from specode.policy import ToolPolicy
from specode.run_store import (
    RunStore,
    summarize_command_result,
    summarize_file_operation,
    summarize_web_search,
)
from specode.runtime import FakeAgentRuntime
from specode.schemas import RoleRunRequest
from specode.workspace_tools import WorkspaceTools


def test_run_store_writes_compact_role_record(tmp_path: Path) -> None:
    store = RunStore(tmp_path, clock=lambda: datetime(2026, 5, 3, tzinfo=UTC))
    result = FakeAgentRuntime().run_role(
        RoleRunRequest(
            task_name="specode-v0-cli-agent",
            role="reviewer",
            task="Task 16",
        )
    )

    record = store.write_result(result)

    assert record.run_id == "0001-reviewer"
    assert store.read_run("specode-v0-cli-agent", "0001-reviewer").role == "reviewer"


def test_run_store_assigns_stable_sequential_run_ids(tmp_path: Path) -> None:
    store = RunStore(tmp_path, clock=lambda: datetime(2026, 5, 3, tzinfo=UTC))
    runtime = FakeAgentRuntime()

    first = store.write_result(
        runtime.run_role(
            RoleRunRequest(
                task_name="specode-v0-cli-agent",
                role="developer",
                task="Task 16",
            )
        )
    )
    second = store.write_result(
        runtime.run_role(
            RoleRunRequest(
                task_name="specode-v0-cli-agent",
                role="tester",
                task="Task 16",
            )
        )
    )

    assert [first.run_id, second.run_id] == ["0001-developer", "0002-tester"]


def test_run_records_keep_command_and_file_summaries_compact(tmp_path: Path) -> None:
    command_result = LocalExecutionBackend(
        tmp_path,
        policy=ToolPolicy.read_only(workspace_root=tmp_path),
    ).run_command(
        CommandRequest.from_argv(
            [sys.executable, "-c", "print('verbose output')"],
            purpose="test",
        )
    )
    file_result = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    ).create_file("notes.txt", "content that should not be persisted\n", approved_scope=True)
    role_result = FakeAgentRuntime().run_role(
        RoleRunRequest(
            task_name="specode-v0-cli-agent",
            role="developer",
            task="Task 16",
            command_summaries=[summarize_command_result(command_result)],
            file_summaries=[summarize_file_operation(file_result)],
        )
    )

    record = RunStore(tmp_path).write_result(role_result)
    raw_json = (tmp_path / "tasks" / "specode-v0-cli-agent" / "runs" / f"{record.run_id}.json").read_text()

    assert '"stdout"' not in raw_json
    assert '"stderr"' not in raw_json
    assert '"env_keys"' not in raw_json
    assert "content that should not be persisted" not in raw_json
    assert record.commands[0].status == "ok"
    assert "-c" in record.commands[0].command
    assert record.files[0].action == "created"


def test_run_records_keep_web_search_summaries_compact(tmp_path: Path) -> None:
    web_summary = summarize_web_search(
        SimpleNamespace(
            query="Pydantic AI tool calls",
            status="ok",
            result_count=1,
            sources=["https://pydantic.dev/docs/ai/tools-toolsets/tools/"],
            backend="fake",
            snippets=["raw page-like snippet that should not be persisted"],
        )
    )
    role_result = FakeAgentRuntime().run_role(
        RoleRunRequest(
            task_name="specode-v0-cli-agent",
            role="developer",
            task="Task 16",
        )
    ).model_copy(update={"web_summaries": [web_summary]})

    record = RunStore(tmp_path).write_result(role_result)
    raw_json = (tmp_path / "tasks" / "specode-v0-cli-agent" / "runs" / f"{record.run_id}.json").read_text()

    assert '"web_searches"' in raw_json
    assert "raw page-like snippet" not in raw_json
    assert record.web_searches[0].query == "Pydantic AI tool calls"
    assert record.web_searches[0].sources == [
        "https://pydantic.dev/docs/ai/tools-toolsets/tools/"
    ]


def test_run_records_read_old_records_without_web_searches(tmp_path: Path) -> None:
    store = RunStore(tmp_path, clock=lambda: datetime(2026, 5, 3, tzinfo=UTC))
    record = store.write_result(
        FakeAgentRuntime().run_role(
            RoleRunRequest(
                task_name="specode-v0-cli-agent",
                role="reviewer",
                task="Task 16",
            )
        )
    )
    path = tmp_path / "tasks" / "specode-v0-cli-agent" / "runs" / f"{record.run_id}.json"
    raw = path.read_text().replace(',"web_searches":[]', "")
    path.write_text(raw)

    assert store.read_run("specode-v0-cli-agent", record.run_id).web_searches == []
