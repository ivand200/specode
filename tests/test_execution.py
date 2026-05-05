from __future__ import annotations

import sys
from pathlib import Path

from specode.execution import CommandRequest, LocalExecutionBackend
from specode.policy import ToolPolicy


def test_allowed_safe_command_runs_and_captures_output(tmp_path: Path) -> None:
    backend = LocalExecutionBackend(tmp_path, policy=ToolPolicy.read_only())
    request = CommandRequest.from_argv(
        [sys.executable, "-c", "print('hello from backend')"],
        purpose="test",
    )

    result = backend.run_command(request)

    assert result.ok
    assert result.stdout == "hello from backend\n"
    assert result.exit_code == 0
    assert result.policy.allowed


def test_denied_commands_do_not_run(tmp_path: Path) -> None:
    backend = LocalExecutionBackend(tmp_path, policy=ToolPolicy.read_only())

    result = backend.run_command(
        CommandRequest.from_argv(["touch", "blocked.txt"], cwd=tmp_path)
    )

    assert result.status == "blocked"
    assert result.policy.denied
    assert not (tmp_path / "blocked.txt").exists()


def test_ask_commands_do_not_run_without_approval(tmp_path: Path) -> None:
    backend = LocalExecutionBackend(tmp_path, policy=ToolPolicy.workspace_write())
    request = CommandRequest.from_argv(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('asked.txt').write_text('nope')",
        ],
        cwd=tmp_path,
        concerns=frozenset({"mutates_state"}),
    )

    result = backend.run_command(request)

    assert result.status == "blocked"
    assert result.policy.needs_approval
    assert not (tmp_path / "asked.txt").exists()


def test_command_timeout_is_reported(tmp_path: Path) -> None:
    backend = LocalExecutionBackend(tmp_path, policy=ToolPolicy.read_only())

    result = backend.run_command(
        CommandRequest.from_argv(
            [sys.executable, "-c", "import time; time.sleep(2)"],
            timeout_seconds=0.1,
        )
    )

    assert result.status == "timeout"
    assert result.timed_out
    assert result.exit_code is None


def test_environment_only_exposes_allowlisted_keys(tmp_path: Path) -> None:
    backend = LocalExecutionBackend(tmp_path, policy=ToolPolicy.read_only())

    result = backend.run_command(
        CommandRequest.from_argv(
            [
                sys.executable,
                "-c",
                (
                    "import os; "
                    "print(os.environ.get('SPECODE_VISIBLE'), "
                    "os.environ.get('SPECODE_SECRET'))"
                ),
            ],
            env_allowlist=("SPECODE_VISIBLE",),
            env={
                "SPECODE_VISIBLE": "allowed",
                "SPECODE_SECRET": "should-not-leak",
            },
        )
    )

    assert result.ok
    assert result.stdout == "allowed None\n"
    assert result.env_keys == ("SPECODE_VISIBLE",)


def test_sandbox_preferred_unavailable_blocks_local_downgrade(
    tmp_path: Path,
) -> None:
    backend = LocalExecutionBackend(tmp_path, policy=ToolPolicy.full_access())
    request = CommandRequest.from_argv(
        [
            sys.executable,
            "-c",
            "from pathlib import Path; Path('sandboxed.txt').write_text('nope')",
        ],
        cwd=tmp_path,
        sandbox_preference="preferred",
    )

    result = backend.run_command(request)

    assert result.status == "blocked"
    assert result.policy.needs_approval
    assert result.policy.blockers[0].code == "sandbox-preferred-unavailable"
    assert not (tmp_path / "sandboxed.txt").exists()


def test_sandbox_required_unavailable_denies_local_execution(tmp_path: Path) -> None:
    backend = LocalExecutionBackend(tmp_path, policy=ToolPolicy.full_access())

    result = backend.run_command(
        CommandRequest.from_argv(
            [sys.executable, "-c", "print('must not run')"],
            sandbox_preference="required",
        )
    )

    assert result.status == "blocked"
    assert result.policy.denied
    assert result.stdout == ""
