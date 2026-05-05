"""Typer CLI shell and deterministic command router for SpeCode V0."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import typer

from specode.artifacts import (
    ArtifactStore,
    ArtifactStoreError,
    TaskSourceProvenance,
    hash_text,
)
from specode.commands import CommandCatalog, default_command_catalog
from specode.completion import FileCandidate, complete
from specode.interactive import PromptConfig, run_interactive_shell
from specode.runtime import (
    ChatRequest,
    ChatRuntime,
    FakeChatRuntime,
)
from specode.steering import build_steering_docs
from specode.ui import TerminalUI
from specode.workflow import WorkflowEngine


class RouteKind(str, Enum):
    """Top-level routing categories for user input."""

    CHAT = "chat"
    COMMAND = "command"
    EXIT = "exit"
    EMPTY = "empty"
    UNKNOWN = "unknown"
    RESERVED = "reserved"


@dataclass(frozen=True)
class RouteResult:
    """Observable result of routing one user input line."""

    kind: RouteKind
    text: str
    command: str | None = None
    creates_sdd_artifacts: bool = False


class CommandRouter:
    """Route ordinary chat and slash commands without live LLM side effects."""

    def __init__(
        self,
        workspace_root: Path | str | None = None,
        *,
        chat_runtime: ChatRuntime | None = None,
        command_catalog: CommandCatalog | None = None,
    ) -> None:
        self.chat_runtime = chat_runtime or _default_chat_runtime()
        self.command_catalog = command_catalog or default_command_catalog()
        self.store: ArtifactStore | None = None
        self.workflow: WorkflowEngine | None = None
        if workspace_root is not None:
            self.store = ArtifactStore(workspace_root)
            self.workflow = WorkflowEngine(self.store)

    def route(self, raw_input: str) -> RouteResult:
        user_input = raw_input.strip()

        if not user_input:
            return RouteResult(RouteKind.EMPTY, "")

        if user_input in {"/exit", "/quit"}:
            return RouteResult(RouteKind.EXIT, "Session ended.", command=user_input[1:])

        if user_input[0] in {"@", "!"}:
            return RouteResult(
                RouteKind.RESERVED,
                (
                    f"'{user_input[0]}' input is reserved for a future command mode "
                    "and was not sent to chat."
                ),
            )

        if not user_input.startswith("/"):
            chat_result = self.chat_runtime.run_chat(ChatRequest(message=user_input))
            return RouteResult(RouteKind.CHAT, chat_result.text)

        command, _, argument = user_input[1:].partition(" ")
        command = command.strip().lower()
        argument = argument.strip()
        command_definition = self.command_catalog.lookup(command)
        if command_definition is None:
            return RouteResult(
                RouteKind.UNKNOWN,
                f"Unknown slash command: /{command}",
                command=command,
            )

        command = command_definition.name

        if command == "exit":
            return RouteResult(RouteKind.EXIT, "Session ended.", command=command)

        if command == "spec":
            if self.store is None or self.workflow is None:
                detail = f" Received: {argument}" if argument else ""
                return RouteResult(
                    RouteKind.COMMAND,
                    (
                        "/spec is recognized, but its workflow side effects belong "
                        f"to a later SpeCode V0 task.{detail}"
                    ),
                    command=command,
                )
            return self._route_spec(argument)

        if command == "steering":
            return self._route_steering(argument)

        return self._placeholder_result(command, argument)

    def _route_spec(self, argument: str) -> RouteResult:
        if not argument:
            return RouteResult(
                RouteKind.COMMAND,
                "Usage: /spec <task description or path-to-task.md>",
                command="spec",
            )

        normalized_file_argument = self._normalize_file_reference_argument(argument)
        if self._looks_like_markdown_path(normalized_file_argument):
            return self._route_spec_file(normalized_file_argument)

        task_name = self.workflow.derive_task_slug(argument)
        transition = self.workflow.start(task_name, argument)
        if transition.created and not transition.blocked:
            provenance = TaskSourceProvenance.from_text(argument)
            self.store.write_imported_task(task_name, argument, provenance)

        action = "Resumed" if transition.resumed else "Created"
        return RouteResult(
            RouteKind.COMMAND,
            (
                f"{action} /spec task '{task_name}'. {transition.message} "
                f"Next: {transition.recommended_next_step}"
            ),
            command="spec",
            creates_sdd_artifacts=transition.created,
        )

    def _route_spec_file(self, argument: str) -> RouteResult:
        try:
            source_path, source_text = self.store.read_source_task_file(
                self.store.workspace_root / argument
            )
        except ArtifactStoreError as exc:
            return RouteResult(RouteKind.COMMAND, str(exc), command="spec")

        task_name = self.workflow.derive_file_task_slug(source_path, source_text)
        current_hash = hash_text(source_text)

        existing_provenance = self.store.read_task_provenance(task_name)
        if (
            existing_provenance is not None
            and existing_provenance.kind == "file"
            and existing_provenance.source_sha256 != current_hash
        ):
            transition = self.workflow.record_source_drift(
                task_name,
                source_path=existing_provenance.source_path or source_path.as_posix(),
                imported_hash=existing_provenance.source_sha256,
                current_hash=current_hash,
            )
            return RouteResult(
                RouteKind.COMMAND,
                (
                    f"Source drift detected for /spec task '{task_name}'. "
                    f"{transition.message}"
                ),
                command="spec",
                creates_sdd_artifacts=False,
            )

        transition = self.workflow.start(task_name, source_text)
        if transition.created and not transition.blocked:
            provenance = TaskSourceProvenance.from_file(
                source_path,
                source_text,
                self.store.workspace_root,
            )
            self.store.write_imported_task(task_name, source_text, provenance)

        action = "Resumed" if transition.resumed else "Created"
        return RouteResult(
            RouteKind.COMMAND,
            (
                f"{action} /spec task '{task_name}' from {source_path.name}. "
                f"{transition.message} Next: {transition.recommended_next_step}"
            ),
            command="spec",
            creates_sdd_artifacts=transition.created,
        )

    def _route_steering(self, argument: str) -> RouteResult:
        if self.store is None:
            return self._placeholder_result("steering", argument)
        if argument:
            return RouteResult(
                RouteKind.COMMAND,
                "Usage: /steering",
                command="steering",
            )

        statuses = self.store.ensure_steering_docs(
            build_steering_docs(self.store.workspace_root)
        )
        created_docs = [doc for doc, status in statuses.items() if status == "created"]
        updated_docs = [doc for doc, status in statuses.items() if status == "updated"]
        preserved_docs = [doc for doc, status in statuses.items() if status == "preserved"]

        message_parts: list[str] = []
        if created_docs:
            message_parts.append(f"Created from repository scan: {', '.join(created_docs)}.")
        if updated_docs:
            message_parts.append(f"Refreshed default placeholders: {', '.join(updated_docs)}.")
        if preserved_docs:
            message_parts.append(f"Preserved existing: {', '.join(preserved_docs)}.")

        if message_parts:
            message = "Steering docs ready. " + " ".join(message_parts)
        else:
            message = "Steering docs already exist."

        return RouteResult(
            RouteKind.COMMAND,
            message,
            command="steering",
            creates_sdd_artifacts=False,
        )

    def _placeholder_result(self, command: str, argument: str) -> RouteResult:
        detail = f" Received: {argument}" if argument else ""
        return RouteResult(
            RouteKind.COMMAND,
            (
                f"/{command} is recognized, but its workflow side effects belong "
                f"to a later SpeCode V0 task.{detail}"
            ),
            command=command,
        )

    def _looks_like_markdown_path(self, argument: str) -> bool:
        candidate = Path(argument)
        return candidate.suffix.lower() == ".md"

    def _normalize_file_reference_argument(self, argument: str) -> str:
        if not argument.startswith("@"):
            return argument
        return argument[1:].replace("\\ ", " ")


app = typer.Typer(
    add_completion=False,
    help="SpeCode V0 CLI coding agent.",
    invoke_without_command=True,
)


def render_result(result: RouteResult, ui: TerminalUI) -> None:
    """Render one routed result with restrained styling."""

    if result.kind == RouteKind.EMPTY:
        return
    if result.kind in {RouteKind.UNKNOWN, RouteKind.RESERVED}:
        ui.warning(result.text)
        return
    if result.kind == RouteKind.EXIT:
        ui.notice(result.text)
        return

    ui.assistant(result.text)


def _default_chat_runtime() -> ChatRuntime:
    try:
        from specode.pydantic_runtime import OpenAIChatRuntime, PydanticRuntimeConfig
    except (ImportError, AttributeError):
        return FakeChatRuntime()

    return OpenAIChatRuntime(PydanticRuntimeConfig.from_env(dotenv_path=Path.cwd() / ".env"))


def run_interactive(
    input_func: Callable[[str], str] | None = None,
    router: CommandRouter | None = None,
    ui: TerminalUI | None = None,
) -> None:
    """Run the deterministic interactive shell until EOF or /exit."""

    active_router = router or CommandRouter(Path.cwd())
    active_ui = ui or TerminalUI()
    active_ui.intro()
    runtime_blocker = _chat_runtime_configuration_blocker(active_router)
    if runtime_blocker is not None:
        active_ui.warning(runtime_blocker)

    if input_func is not None or not sys.stdin.isatty():
        _run_line_prompt_loop(input_func or typer.prompt, active_router, active_ui)
        return

    workspace_root = (
        active_router.store.workspace_root if active_router.store is not None else Path.cwd()
    )

    def completion_engine(text: str, cursor_position: int) -> tuple[object, ...]:
        return complete(
            text,
            cursor_position,
            catalog=active_router.command_catalog,
            file_candidates=_file_completion_candidates(workspace_root),
        )

    run_interactive_shell(
        active_router,
        lambda result: render_result(result, active_ui),
        completion_engine=completion_engine,
        prompt_config=PromptConfig(prompt_text="specode> "),
    )


def _run_line_prompt_loop(
    input_func: Callable[[str], str],
    active_router: CommandRouter,
    active_ui: TerminalUI,
) -> None:
    """Run a basic line prompt for tests and piped stdin."""

    while True:
        try:
            line = input_func("specode")
        except (EOFError, KeyboardInterrupt):
            active_ui.notice("Session ended.")
            return

        result = active_router.route(line)
        render_result(result, active_ui)
        if result.kind == RouteKind.EXIT:
            return


_SKIP_COMPLETION_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "target",
        "vendor",
        "venv",
    }
)


def _file_completion_candidates(
    workspace_root: Path,
    *,
    max_entries: int = 4000,
) -> tuple[FileCandidate, ...]:
    """Return workspace-relative file and directory candidates without reading files."""

    candidates: list[FileCandidate] = []
    try:
        for root, dir_names, file_names in os.walk(workspace_root):
            dir_names[:] = sorted(
                name
                for name in dir_names
                if name.lower() not in _SKIP_COMPLETION_DIRS
            )
            current_root = Path(root)
            for dirname in dir_names:
                relative = _relative_completion_path(workspace_root, current_root / dirname)
                if relative:
                    candidates.append(FileCandidate(relative, is_directory=True))
                if len(candidates) >= max_entries:
                    return tuple(candidates)

            for filename in sorted(file_names):
                relative = _relative_completion_path(workspace_root, current_root / filename)
                if relative:
                    candidates.append(FileCandidate(relative))
                if len(candidates) >= max_entries:
                    return tuple(candidates)
    except OSError:
        return tuple(candidates)

    return tuple(candidates)


def _relative_completion_path(workspace_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return ""


def _chat_runtime_configuration_blocker(router: CommandRouter) -> str | None:
    config = getattr(router.chat_runtime, "config", None)
    configuration_blocker = getattr(config, "configuration_blocker", None)
    if callable(configuration_blocker):
        blocker = configuration_blocker()
        return str(blocker) if blocker else None
    return None


@app.callback()
def cli() -> None:
    """Open the interactive SpeCode shell."""

    run_interactive()


def main() -> None:
    """Console script entry point."""

    app()
