from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from specode.execution import CommandRequest, CommandResult, LocalExecutionBackend
from specode.policy import ToolPolicy
from specode.workspace_tools import WorkspaceToolResult, WorkspaceTools


def test_tool_and_execution_safety_boundary(tmp_path: Path) -> None:
    result = exercise_tool_and_execution_safety(tmp_path)

    assert result.read_only_create.status == "blocked"
    assert result.read_only_create.policy.denied
    assert result.read_only_update.status == "blocked"
    assert result.original_file.read_text(encoding="utf-8") == "print('original')\n"
    assert not result.blocked_read_only_file.exists()

    assert result.scoped_create.ok
    assert result.scoped_update.ok
    assert result.scoped_file.read_text(encoding="utf-8") == "print('updated')\n"
    assert result.outside_update.status == "blocked"
    assert result.outside_update.policy.blockers[0].code == "outside-workspace"

    assert result.default_delete.status == "blocked"
    assert result.default_delete.policy.needs_approval
    assert result.default_delete.policy.blockers[0].code == "destructive-action"
    assert result.delete_target.exists()

    assert result.denied_command.status == "blocked"
    assert result.denied_command.policy.denied
    assert result.denied_command.policy.blockers[0].code == "destructive-command"
    assert result.command_target.exists()

    assert result.safe_command.ok
    assert result.safe_command.command == (
        sys.executable,
        "-c",
        "print('safe command result')",
    )
    assert result.safe_command.cwd == str(tmp_path)
    assert result.safe_command.stdout == "safe command result\n"
    assert result.safe_command.exit_code == 0
    assert result.safe_command.policy.allowed
    assert result.safe_command.backend == "local"


@dataclass(frozen=True)
class SafetyBoundaryResult:
    original_file: Path
    blocked_read_only_file: Path
    scoped_file: Path
    delete_target: Path
    command_target: Path
    read_only_create: WorkspaceToolResult
    read_only_update: WorkspaceToolResult
    scoped_create: WorkspaceToolResult
    scoped_update: WorkspaceToolResult
    outside_update: WorkspaceToolResult
    default_delete: WorkspaceToolResult
    denied_command: CommandResult
    safe_command: CommandResult


def exercise_tool_and_execution_safety(workspace: Path) -> SafetyBoundaryResult:
    source = workspace / "src" / "app.py"
    source.parent.mkdir()
    source.write_text("print('original')\n", encoding="utf-8")

    read_only_tools = WorkspaceTools(
        workspace,
        policy=ToolPolicy.read_only(workspace_root=workspace),
    )
    read_only_create = read_only_tools.create_file(
        "src/blocked.py",
        "print('blocked')\n",
        approved_scope=True,
    )
    read_only_update = read_only_tools.update_file(
        "src/app.py",
        "print('changed')\n",
        approved_scope=True,
    )

    writable_tools = WorkspaceTools(
        workspace,
        policy=ToolPolicy.workspace_write(workspace_root=workspace),
    )
    scoped_create = writable_tools.create_file(
        "src/scoped.py",
        "print('created')\n",
        approved_scope=True,
    )
    scoped_update = writable_tools.update_file(
        "src/scoped.py",
        "print('updated')\n",
        approved_scope=True,
    )
    outside = workspace.parent / "outside.py"
    outside.write_text("outside\n", encoding="utf-8")
    outside_update = writable_tools.update_file(
        outside,
        "changed\n",
        approved_scope=True,
    )

    delete_target = workspace / "src" / "delete_me.py"
    delete_target.write_text("print('keep')\n", encoding="utf-8")
    default_delete = writable_tools.delete_file(
        "src/delete_me.py",
        approved_scope=True,
    )

    command_target = workspace / "src" / "command_target.py"
    command_target.write_text("print('must survive')\n", encoding="utf-8")
    backend = LocalExecutionBackend(
        workspace,
        policy=ToolPolicy.full_access(workspace_root=workspace),
    )
    denied_command = backend.run_command(
        CommandRequest.from_argv(
            ["rm", "src/command_target.py"],
            cwd=workspace,
            purpose="other",
        )
    )
    safe_command = backend.run_command(
        CommandRequest.from_argv(
            [sys.executable, "-c", "print('safe command result')"],
            cwd=workspace,
            purpose="test",
        )
    )

    return SafetyBoundaryResult(
        original_file=source,
        blocked_read_only_file=workspace / "src" / "blocked.py",
        scoped_file=workspace / "src" / "scoped.py",
        delete_target=delete_target,
        command_target=command_target,
        read_only_create=read_only_create,
        read_only_update=read_only_update,
        scoped_create=scoped_create,
        scoped_update=scoped_update,
        outside_update=outside_update,
        default_delete=default_delete,
        denied_command=denied_command,
        safe_command=safe_command,
    )
