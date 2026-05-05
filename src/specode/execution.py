"""Policy-aware command execution backends for SpeCode agents."""

from __future__ import annotations

import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Mapping

from specode.policy import (
    CommandConcern,
    CommandOperation,
    PolicyDecision,
    SandboxPreference,
    ToolPolicy,
    ToolPolicyError,
)


CommandPurpose = Literal[
    "test",
    "lint",
    "build",
    "dev-server",
    "migration",
    "install",
    "other",
]
CommandStatus = Literal["ok", "failed", "blocked", "timeout", "error"]


@dataclass(frozen=True)
class CommandRequest:
    """Structured command request routed through ToolPolicy before execution."""

    argv: tuple[str, ...]
    cwd: Path | str | None = None
    timeout_seconds: float = 30.0
    env_allowlist: tuple[str, ...] = ("PATH",)
    env: Mapping[str, str] = field(default_factory=dict)
    purpose: CommandPurpose = "other"
    approved_scope: bool = False
    concerns: frozenset[CommandConcern] = field(default_factory=frozenset)
    explicit_blocker: str | None = None
    sandbox_preference: SandboxPreference = "none"

    def __post_init__(self) -> None:
        argv = tuple(str(arg) for arg in self.argv)
        if not argv:
            raise ToolPolicyError("command argv must not be empty")
        if self.timeout_seconds <= 0:
            raise ToolPolicyError("command timeout must be greater than zero")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(
            self,
            "env_allowlist",
            tuple(str(name) for name in self.env_allowlist),
        )
        object.__setattr__(
            self,
            "env",
            {str(key): str(value) for key, value in self.env.items()},
        )
        object.__setattr__(self, "concerns", frozenset(self.concerns))

    @classmethod
    def from_argv(
        cls,
        argv: tuple[str, ...] | list[str],
        **kwargs: object,
    ) -> "CommandRequest":
        return cls(tuple(argv), **kwargs)

    @property
    def command_text(self) -> str:
        return CommandOperation(self.argv).command_text


@dataclass(frozen=True)
class CommandResult:
    """Structured command execution result for manager and role agents."""

    command: tuple[str, ...]
    cwd: str
    status: CommandStatus
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    started_at: datetime
    ended_at: datetime
    timeout_seconds: float
    purpose: CommandPurpose
    policy: PolicyDecision
    backend: Literal["local"] = "local"
    sandbox_preference: SandboxPreference = "none"
    env_keys: tuple[str, ...] = ()
    blocker: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class ExecutionBackend(ABC):
    """Abstract command execution boundary for local and future sandbox backends."""

    @abstractmethod
    def run_command(self, request: CommandRequest) -> CommandResult:
        """Run a policy-approved command and return a structured result."""


class LocalExecutionBackend(ExecutionBackend):
    """Host-process command execution for low-risk V0 workflows."""

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        *,
        policy: ToolPolicy | None = None,
        sandbox_available: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None
        if policy is None:
            self.policy = ToolPolicy.read_only(workspace_root=self.workspace_root)
        elif policy.workspace_root != self.workspace_root:
            self.policy = ToolPolicy(policy.mode, workspace_root=self.workspace_root)
        else:
            self.policy = policy
        self.sandbox_available = sandbox_available

    def run_command(self, request: CommandRequest) -> CommandResult:
        cwd, cwd_blocker = self._resolve_cwd(request.cwd)
        policy = self._decide(request, cwd, cwd_blocker)
        started_at = _now()

        if not policy.allowed:
            return self._result(
                request,
                cwd,
                policy,
                "blocked",
                None,
                "",
                "",
                started_at,
                _now(),
                blocker=policy.blocker_reason
                or policy.required_approval
                or policy.reason,
            )

        if cwd_blocker is not None:
            return self._result(
                request,
                cwd,
                policy,
                "error",
                None,
                "",
                cwd_blocker,
                started_at,
                _now(),
                blocker=cwd_blocker,
            )

        env = self._build_env(request)
        try:
            completed = subprocess.run(
                request.argv,
                cwd=str(cwd),
                env=env,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return self._result(
                request,
                cwd,
                policy,
                "timeout",
                None,
                _text_or_empty(exc.stdout),
                _text_or_empty(exc.stderr),
                started_at,
                _now(),
                timed_out=True,
                blocker="Command timed out.",
                env_keys=tuple(sorted(env)),
            )
        except OSError as exc:
            return self._result(
                request,
                cwd,
                policy,
                "error",
                None,
                "",
                str(exc),
                started_at,
                _now(),
                blocker=str(exc),
                env_keys=tuple(sorted(env)),
            )

        status: CommandStatus = "ok" if completed.returncode == 0 else "failed"
        return self._result(
            request,
            cwd,
            policy,
            status,
            completed.returncode,
            completed.stdout,
            completed.stderr,
            started_at,
            _now(),
            env_keys=tuple(sorted(env)),
        )

    def _decide(
        self,
        request: CommandRequest,
        cwd: Path,
        cwd_blocker: str | None,
    ) -> PolicyDecision:
        explicit_blocker = request.explicit_blocker or cwd_blocker
        return self.policy.decide_command(
            CommandOperation.from_argv(
                request.argv,
                cwd=cwd,
                approved_scope=request.approved_scope,
                concerns=request.concerns,
                sandbox_preference=request.sandbox_preference,
                sandbox_available=self.sandbox_available,
                explicit_blocker=explicit_blocker,
                purpose=request.purpose,
            )
        )

    def _resolve_cwd(self, cwd: Path | str | None) -> tuple[Path, str | None]:
        raw_cwd = self.workspace_root if cwd is None else Path(cwd)
        if raw_cwd is None:
            raw_cwd = Path.cwd()
        elif self.workspace_root is not None and not raw_cwd.is_absolute():
            raw_cwd = self.workspace_root / raw_cwd

        resolved = raw_cwd.resolve()
        if self.workspace_root is not None:
            try:
                resolved.relative_to(self.workspace_root)
            except ValueError:
                return resolved, "Command cwd is outside the configured workspace."

        if not resolved.exists():
            return resolved, "Command cwd does not exist."
        if not resolved.is_dir():
            return resolved, "Command cwd is not a directory."
        return resolved, None

    def _build_env(self, request: CommandRequest) -> dict[str, str]:
        allowed = set(request.env_allowlist)
        env: dict[str, str] = {
            name: os.environ[name] for name in allowed if name in os.environ
        }
        env.update(
            {
                name: value
                for name, value in request.env.items()
                if name in allowed
            }
        )
        return env

    def _result(
        self,
        request: CommandRequest,
        cwd: Path,
        policy: PolicyDecision,
        status: CommandStatus,
        exit_code: int | None,
        stdout: str,
        stderr: str,
        started_at: datetime,
        ended_at: datetime,
        *,
        timed_out: bool = False,
        env_keys: tuple[str, ...] = (),
        blocker: str | None = None,
    ) -> CommandResult:
        return CommandResult(
            command=request.argv,
            cwd=str(cwd),
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=timed_out,
            started_at=started_at,
            ended_at=ended_at,
            timeout_seconds=request.timeout_seconds,
            purpose=request.purpose,
            policy=policy,
            sandbox_preference=request.sandbox_preference,
            env_keys=env_keys,
            blocker=blocker,
        )


def _now() -> datetime:
    return datetime.now(UTC)


def _text_or_empty(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
