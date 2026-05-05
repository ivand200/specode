"""Policy decisions for SpeCode file and command tools."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Sequence, get_args


PolicyMode = Literal["read-only", "workspace-write", "full-access"]
Decision = Literal["allow", "ask", "deny"]
PathOperationKind = Literal["discover", "read", "create", "update", "delete"]
SandboxPreference = Literal["none", "preferred", "required"]
CommandConcern = Literal[
    "mutates_state",
    "destructive",
    "credentials",
    "network",
    "installs_dependencies",
    "long_running",
    "unsafe",
    "explicit_blocker",
]

VALID_POLICY_MODES = frozenset(get_args(PolicyMode))
READ_PATH_OPERATIONS = frozenset({"discover", "read"})
WRITE_PATH_OPERATIONS = frozenset({"create", "update", "delete"})
ASK_COMMAND_CONCERNS = frozenset(
    {"mutates_state", "network", "installs_dependencies", "long_running"}
)


class ToolPolicyError(ValueError):
    """Raised when policy inputs cannot produce a safe decision."""


@dataclass(frozen=True)
class PolicyBlocker:
    """Structured reason a tool request cannot continue silently."""

    code: str
    message: str
    required_approval: str | None = None


@dataclass(frozen=True)
class PathOperation:
    """Metadata for a requested filesystem operation."""

    operation: PathOperationKind
    path: Path | str
    approved_scope: bool = False
    approved_destructive: bool = False
    destructive: bool = False
    explicit_blocker: str | None = None
    purpose: str | None = None

    @property
    def target(self) -> str:
        return str(self.path)


@dataclass(frozen=True)
class CommandOperation:
    """Metadata for a requested command execution."""

    argv: Sequence[str]
    cwd: Path | str | None = None
    approved_scope: bool = False
    concerns: frozenset[CommandConcern] = field(default_factory=frozenset)
    sandbox_preference: SandboxPreference = "none"
    sandbox_available: bool = True
    explicit_blocker: str | None = None
    purpose: str | None = None

    def __post_init__(self) -> None:
        argv = tuple(str(arg) for arg in self.argv)
        if not argv:
            raise ToolPolicyError("command argv must not be empty")
        if self.sandbox_preference not in {"none", "preferred", "required"}:
            raise ToolPolicyError(
                f"Unknown sandbox preference: {self.sandbox_preference}"
            )
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "concerns", frozenset(self.concerns))

    @classmethod
    def from_argv(
        cls,
        argv: Sequence[str],
        *,
        cwd: Path | str | None = None,
        approved_scope: bool = False,
        concerns: frozenset[CommandConcern] | None = None,
        sandbox_preference: SandboxPreference = "none",
        sandbox_available: bool = True,
        explicit_blocker: str | None = None,
        purpose: str | None = None,
        infer_concerns: bool = True,
    ) -> "CommandOperation":
        inferred = infer_command_concerns(argv) if infer_concerns else frozenset()
        return cls(
            argv=tuple(argv),
            cwd=cwd,
            approved_scope=approved_scope,
            concerns=inferred | frozenset(concerns or ()),
            sandbox_preference=sandbox_preference,
            sandbox_available=sandbox_available,
            explicit_blocker=explicit_blocker,
            purpose=purpose,
        )

    @property
    def command_text(self) -> str:
        return shlex.join(tuple(self.argv))


@dataclass(frozen=True)
class PolicyDecision:
    """Structured allow/ask/deny result returned by ToolPolicy."""

    operation: str
    mode: PolicyMode
    decision: Decision
    reason: str
    target_path: str | None = None
    command: tuple[str, ...] | None = None
    cwd: str | None = None
    purpose: str | None = None
    concerns: frozenset[CommandConcern] = field(default_factory=frozenset)
    sandbox_preference: SandboxPreference = "none"
    sandbox_available: bool = True
    blockers: tuple[PolicyBlocker, ...] = ()
    required_approval: str | None = None

    @property
    def allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def needs_approval(self) -> bool:
        return self.decision == "ask"

    @property
    def denied(self) -> bool:
        return self.decision == "deny"

    @property
    def blocker_reason(self) -> str | None:
        if not self.blockers:
            return None
        return "; ".join(blocker.message for blocker in self.blockers)


class ToolPolicy:
    """Decide whether SpeCode tools may perform file or command operations."""

    def __init__(
        self,
        mode: PolicyMode = "read-only",
        *,
        workspace_root: Path | str | None = None,
    ) -> None:
        if mode not in VALID_POLICY_MODES:
            raise ToolPolicyError(f"Unknown policy mode: {mode}")
        self.mode = mode
        self.workspace_root = Path(workspace_root).resolve() if workspace_root else None

    @classmethod
    def read_only(
        cls,
        *,
        workspace_root: Path | str | None = None,
    ) -> "ToolPolicy":
        return cls("read-only", workspace_root=workspace_root)

    @classmethod
    def workspace_write(
        cls,
        *,
        workspace_root: Path | str | None = None,
    ) -> "ToolPolicy":
        return cls("workspace-write", workspace_root=workspace_root)

    @classmethod
    def full_access(
        cls,
        *,
        workspace_root: Path | str | None = None,
    ) -> "ToolPolicy":
        return cls("full-access", workspace_root=workspace_root)

    def decide_path(self, request: PathOperation) -> PolicyDecision:
        target_path, scope_blocker = self._path_target_and_scope_blocker(request.path)
        if request.explicit_blocker is not None:
            return self._deny_path(
                request,
                target_path,
                PolicyBlocker("explicit-blocker", request.explicit_blocker),
            )
        if scope_blocker is not None:
            return self._deny_path(request, target_path, scope_blocker)

        operation = request.operation
        if operation in READ_PATH_OPERATIONS:
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="allow",
                reason="Read-only filesystem operation is allowed.",
                target_path=target_path,
                purpose=request.purpose,
            )

        if operation not in WRITE_PATH_OPERATIONS:
            raise ToolPolicyError(f"Unknown path operation: {operation}")

        if self.mode == "read-only":
            return self._deny_path(
                request,
                target_path,
                PolicyBlocker(
                    "read-only-mutation",
                    f"{operation} is not allowed while policy mode is read-only.",
                ),
            )

        if operation == "delete" or request.destructive:
            if request.approved_destructive:
                if self.mode == "workspace-write" and not request.approved_scope:
                    return PolicyDecision(
                        operation=operation,
                        mode=self.mode,
                        decision="ask",
                        reason=(
                            "Workspace-write requires accepted-scope approval "
                            "for mutations."
                        ),
                        target_path=target_path,
                        purpose=request.purpose,
                        required_approval=(
                            "Confirm this file mutation is inside the approved "
                            "task scope."
                        ),
                    )
                return PolicyDecision(
                    operation=operation,
                    mode=self.mode,
                    decision="allow",
                    reason=(
                        f"{operation} is explicitly allowed by {self.mode} policy."
                    ),
                    target_path=target_path,
                    purpose=request.purpose,
                )
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="ask",
                reason="Destructive file operations require explicit approval.",
                target_path=target_path,
                purpose=request.purpose,
                blockers=(
                    PolicyBlocker(
                        "destructive-action",
                        "Deletion or destructive mutation cannot continue silently.",
                        "Approve the destructive file operation.",
                    ),
                ),
                required_approval="Approve the destructive file operation.",
            )

        if self.mode == "workspace-write" and not request.approved_scope:
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="ask",
                reason="Workspace-write requires accepted-scope approval for mutations.",
                target_path=target_path,
                purpose=request.purpose,
                required_approval="Confirm this file mutation is inside the approved task scope.",
            )

        return PolicyDecision(
            operation=operation,
            mode=self.mode,
            decision="allow",
            reason=f"{operation} is allowed by {self.mode} policy.",
            target_path=target_path,
            purpose=request.purpose,
        )

    def decide_command(self, request: CommandOperation) -> PolicyDecision:
        concerns = frozenset(request.concerns) | infer_command_concerns(request.argv)
        if request.explicit_blocker is not None:
            concerns |= {"explicit_blocker"}

        command = tuple(request.argv)
        cwd = str(Path(request.cwd).resolve()) if request.cwd is not None else None
        operation = "command"
        sandbox_blocker = _sandbox_blocker(
            request.sandbox_preference,
            request.sandbox_available,
        )
        if sandbox_blocker is not None and request.sandbox_preference == "required":
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="deny",
                reason=sandbox_blocker.message,
                command=command,
                cwd=cwd,
                purpose=request.purpose,
                concerns=concerns,
                sandbox_preference=request.sandbox_preference,
                sandbox_available=request.sandbox_available,
                blockers=(sandbox_blocker,),
                required_approval=sandbox_blocker.required_approval,
            )

        blocker = self._command_deny_blocker(concerns, request.explicit_blocker)
        if blocker is not None:
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="deny",
                reason=blocker.message,
                command=command,
                cwd=cwd,
                purpose=request.purpose,
                concerns=concerns,
                sandbox_preference=request.sandbox_preference,
                sandbox_available=request.sandbox_available,
                blockers=(blocker,),
            )

        if sandbox_blocker is not None:
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="ask",
                reason=sandbox_blocker.message,
                command=command,
                cwd=cwd,
                purpose=request.purpose,
                concerns=concerns,
                sandbox_preference=request.sandbox_preference,
                sandbox_available=request.sandbox_available,
                blockers=(sandbox_blocker,),
                required_approval=sandbox_blocker.required_approval,
            )

        asking_concerns = concerns & ASK_COMMAND_CONCERNS
        if self.mode == "read-only" and "mutates_state" in concerns:
            blocker = PolicyBlocker(
                "read-only-command-mutation",
                "Command may mutate state while policy mode is read-only.",
            )
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="deny",
                reason=blocker.message,
                command=command,
                cwd=cwd,
                purpose=request.purpose,
                concerns=concerns,
                sandbox_preference=request.sandbox_preference,
                sandbox_available=request.sandbox_available,
                blockers=(blocker,),
            )

        if self.mode == "read-only" and asking_concerns:
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="ask",
                reason="Read-only mode requires approval for command concerns.",
                command=command,
                cwd=cwd,
                purpose=request.purpose,
                concerns=concerns,
                sandbox_preference=request.sandbox_preference,
                sandbox_available=request.sandbox_available,
                required_approval=_command_approval(concerns),
            )

        if self.mode == "workspace-write" and asking_concerns:
            return PolicyDecision(
                operation=operation,
                mode=self.mode,
                decision="ask",
                reason="Workspace-write requires approval for command concerns.",
                command=command,
                cwd=cwd,
                purpose=request.purpose,
                concerns=concerns,
                sandbox_preference=request.sandbox_preference,
                sandbox_available=request.sandbox_available,
                required_approval=_command_approval(concerns),
            )

        return PolicyDecision(
            operation=operation,
            mode=self.mode,
            decision="allow",
            reason=f"Command is allowed by {self.mode} policy.",
            command=command,
            cwd=cwd,
            purpose=request.purpose,
            concerns=concerns,
            sandbox_preference=request.sandbox_preference,
            sandbox_available=request.sandbox_available,
        )

    def _path_target_and_scope_blocker(
        self,
        path: Path | str,
    ) -> tuple[str, PolicyBlocker | None]:
        raw_path = Path(path).expanduser()
        if self.workspace_root is not None and not raw_path.is_absolute():
            raw_path = self.workspace_root / raw_path
        resolved = raw_path.resolve()
        target_path = str(resolved)

        if self.workspace_root is None:
            return target_path, None

        try:
            resolved.relative_to(self.workspace_root)
        except ValueError:
            return target_path, PolicyBlocker(
                "outside-workspace",
                "Path is outside the configured workspace.",
            )
        return target_path, None

    def _deny_path(
        self,
        request: PathOperation,
        target_path: str,
        blocker: PolicyBlocker,
    ) -> PolicyDecision:
        return PolicyDecision(
            operation=request.operation,
            mode=self.mode,
            decision="deny",
            reason=blocker.message,
            target_path=target_path,
            purpose=request.purpose,
            blockers=(blocker,),
            required_approval=blocker.required_approval,
        )

    @staticmethod
    def _command_deny_blocker(
        concerns: frozenset[CommandConcern],
        explicit_blocker: str | None,
    ) -> PolicyBlocker | None:
        if explicit_blocker is not None:
            return PolicyBlocker("explicit-blocker", explicit_blocker)
        if "credentials" in concerns:
            return PolicyBlocker(
                "credentials-required",
                "Command requires credentials, secrets, or external auth.",
            )
        if "destructive" in concerns:
            return PolicyBlocker(
                "destructive-command",
                "Destructive commands cannot continue without manager approval.",
                "Approve the destructive command outside automatic tool execution.",
            )
        if "unsafe" in concerns:
            return PolicyBlocker(
                "unsafe-command",
                "Command is classified as unsafe by policy.",
            )
        return None


def infer_command_concerns(argv: Sequence[str]) -> frozenset[CommandConcern]:
    """Infer coarse command concerns for later execution policy.

    This intentionally stays conservative and transparent; callers can still
    provide explicit concerns when workflow context knows more than argv.
    """

    if not argv:
        raise ToolPolicyError("command argv must not be empty")

    args = tuple(str(arg) for arg in argv)
    executable = Path(args[0]).name
    command_line = " ".join(args).lower()
    concerns: set[CommandConcern] = set()

    if executable in {"sudo", "su", "dd", "mkfs", "mount", "umount"}:
        concerns.add("unsafe")
    if executable in {"sh", "bash", "zsh", "fish"} and "-c" in args:
        concerns.add("unsafe")

    if executable in {"rm", "rmdir"}:
        concerns.update({"mutates_state", "destructive"})
    if executable in {"mv", "cp", "mkdir", "touch"}:
        concerns.add("mutates_state")
    if executable in {"chmod", "chown"}:
        concerns.update({"mutates_state", "unsafe"})
    if executable == "sed" and any(arg.startswith("-i") for arg in args[1:]):
        concerns.add("mutates_state")

    if executable == "git":
        _infer_git_concerns(args, concerns)

    if _looks_like_dependency_install(args):
        concerns.update({"mutates_state", "network", "installs_dependencies"})

    if executable in {"curl", "wget", "ssh", "scp", "rsync"}:
        concerns.add("network")
    if executable in {"docker", "podman"}:
        concerns.update({"mutates_state", "network", "long_running"})
    if executable in {"make", "ninja"} and any(
        word in command_line for word in ("install", "deploy", "publish", "release")
    ):
        concerns.add("mutates_state")

    if any(
        token in command_line
        for token in ("api_key", "apikey", "token=", "password=", "secret=")
    ):
        concerns.add("credentials")
    if executable in {"aws", "gcloud", "az", "op", "vault"}:
        concerns.add("credentials")

    return frozenset(concerns)


def _infer_git_concerns(
    args: tuple[str, ...],
    concerns: set[CommandConcern],
) -> None:
    if len(args) < 2:
        return
    subcommand = args[1]
    if subcommand in {"add", "commit", "merge", "rebase", "checkout", "switch"}:
        concerns.add("mutates_state")
    if subcommand in {"reset", "clean"}:
        concerns.update({"mutates_state", "destructive"})
    if subcommand in {"clone", "fetch", "pull", "push"}:
        concerns.add("network")
    if subcommand == "push":
        concerns.add("mutates_state")


def _looks_like_dependency_install(args: tuple[str, ...]) -> bool:
    if len(args) < 2:
        return False
    executable = Path(args[0]).name
    subcommand = args[1]
    if executable in {"pip", "pip3"} and subcommand == "install":
        return True
    if executable == "uv" and subcommand in {"add", "sync", "pip"}:
        return True
    if executable in {"npm", "pnpm", "yarn"} and subcommand in {"install", "add"}:
        return True
    if executable == "poetry" and subcommand in {"add", "install"}:
        return True
    if executable == "cargo" and subcommand in {"add", "install"}:
        return True
    if executable == "go" and subcommand in {"get", "install"}:
        return True
    return False


def _command_approval(concerns: frozenset[CommandConcern]) -> str:
    labels = {
        "installs_dependencies": "dependency installation",
        "long_running": "long-running execution",
        "mutates_state": "state mutation",
        "network": "network access",
    }
    requested = [labels[concern] for concern in sorted(concerns) if concern in labels]
    if not requested:
        return "Approve command execution."
    return "Approve command " + ", ".join(requested) + "."


def _sandbox_blocker(
    preference: SandboxPreference,
    sandbox_available: bool,
) -> PolicyBlocker | None:
    if preference == "none" or sandbox_available:
        return None
    if preference == "required":
        return PolicyBlocker(
            "sandbox-required-unavailable",
            (
                "Sandbox execution is required for this command, but no sandbox "
                "backend is available."
            ),
        )
    return PolicyBlocker(
        "sandbox-preferred-unavailable",
        (
            "Sandbox execution is preferred for this command, but no sandbox "
            "backend is available."
        ),
        "Approve local command execution without sandbox isolation.",
    )
