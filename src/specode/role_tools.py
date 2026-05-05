"""Model-facing role tools backed by SpeCode safety boundaries."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Sequence

from pydantic_ai import FunctionToolset

from specode.execution import CommandRequest, ExecutionBackend, LocalExecutionBackend
from specode.policy import ToolPolicy
from specode.run_store import summarize_command_result, summarize_file_operation
from specode.schemas import (
    AutomationPolicy,
    CommandRunSummary,
    FileOperationSummary,
    RoleRunRequest,
    WebSearchSummary,
)
from specode.tool_sanitizer import (
    MAX_LIST_FILES,
    MAX_MATCHES_PER_FILE,
    MAX_SEARCH_FILES,
    MAX_WEB_RESULTS,
    BinaryContentError,
    SecretFileError,
    line_window,
    sanitize_command_output,
    sanitize_line,
)
from specode.web_search import (
    BlockedWebSearchBackend,
    WebSearchBackend,
    WebSearchRequest,
)
from specode.workspace_tools import WorkspaceToolResult, WorkspaceTools


ToolStatus = Literal[
    "ok",
    "blocked",
    "error",
    "timeout",
    "not_found",
    "already_exists",
    "binary",
    "failed",
]


@dataclass
class RoleToolSummaryCollector:
    """Collect compact tool summaries during one role run."""

    command_summaries: list[CommandRunSummary] = field(default_factory=list)
    file_summaries: list[FileOperationSummary] = field(default_factory=list)
    web_summaries: list[WebSearchSummary] = field(default_factory=list)


@dataclass
class RoleToolContext:
    """Runtime dependencies for model-facing role tools."""

    request: RoleRunRequest
    workspace_root: Path
    workspace_tools: WorkspaceTools
    execution_backend: ExecutionBackend
    web_search_backend: WebSearchBackend
    collector: RoleToolSummaryCollector = field(default_factory=RoleToolSummaryCollector)
    yolo_execution_backend: ExecutionBackend | None = None

    @property
    def automation_policy(self) -> AutomationPolicy:
        return self.request.automation_policy

    @property
    def approved_scope(self) -> bool:
        return self.request.approved_scope

    @classmethod
    def default(
        cls,
        request: RoleRunRequest,
        *,
        workspace_root: Path | str,
        web_search_backend: WebSearchBackend | None = None,
    ) -> "RoleToolContext":
        root = Path(workspace_root).resolve()
        workspace_policy = ToolPolicy.workspace_write(workspace_root=root)
        return cls(
            request=request,
            workspace_root=root,
            workspace_tools=WorkspaceTools(root, policy=workspace_policy),
            execution_backend=LocalExecutionBackend(root, policy=workspace_policy),
            yolo_execution_backend=LocalExecutionBackend(
                root,
                policy=ToolPolicy.full_access(workspace_root=root),
            ),
            web_search_backend=web_search_backend or BlockedWebSearchBackend(),
        )


class RoleToolsetFactory:
    """Build the approved function toolset for one live role run."""

    def build(self, context: RoleToolContext) -> FunctionToolset:
        """Return Pydantic AI function tools bound to the supplied context."""

        def list_files(path: str = ".") -> dict[str, Any]:
            """List files inside the configured workspace."""

            result = context.workspace_tools.list_files(path)
            context.collector.file_summaries.append(_file_summary(result, context))
            files = [
                {
                    "path": entry.path,
                    "size_bytes": entry.size_bytes,
                }
                for entry in result.files[:MAX_LIST_FILES]
            ]
            return _envelope(
                tool="list_files",
                status=result.status,
                policy=result.policy,
                data={
                    "path": _display_path(result.path, context),
                    "files": files,
                    "file_count": len(result.files),
                },
                summary=context.collector.file_summaries[-1].model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                capped=len(result.files) > len(files),
                blocker=result.blocker,
            )

        def search_files(
            query: str,
            path: str = ".",
            max_matches_per_file: int = MAX_MATCHES_PER_FILE,
        ) -> dict[str, Any]:
            """Search text files inside the configured workspace."""

            result = context.workspace_tools.search_files(
                query,
                path,
                max_matches_per_file=min(max_matches_per_file, MAX_MATCHES_PER_FILE),
            )
            context.collector.file_summaries.append(_file_summary(result, context))
            matches: list[dict[str, Any]] = []
            capped = len(result.matches) > MAX_SEARCH_FILES
            redacted = False
            for file_result in result.matches[:MAX_SEARCH_FILES]:
                safe_matches: list[dict[str, Any]] = []
                for match in file_result.matches[:MAX_MATCHES_PER_FILE]:
                    safe_line = sanitize_line(match.line)
                    redacted = redacted or safe_line.redacted
                    capped = capped or safe_line.capped
                    safe_matches.append(
                        {
                            "line_number": match.line_number,
                            "line": safe_line.text,
                        }
                    )
                matches.append({"path": file_result.path, "matches": safe_matches})

            return _envelope(
                tool="search_files",
                status=result.status,
                policy=result.policy,
                data={
                    "path": _display_path(result.path, context),
                    "matches": matches,
                    "match_file_count": len(result.matches),
                    "redacted": redacted,
                },
                summary=context.collector.file_summaries[-1].model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                capped=capped,
                blocker=result.blocker,
            )

        def read_file(
            path: str,
            start_line: int = 1,
            limit: int = 200,
        ) -> dict[str, Any]:
            """Read a line-window from a workspace text file."""

            result = context.workspace_tools.read_file(path)
            context.collector.file_summaries.append(_file_summary(result, context))
            data: dict[str, Any] = {"path": _display_path(result.path, context)}
            capped = False
            blocker = result.blocker
            status: str = result.status
            if result.content is not None and result.status == "ok":
                try:
                    window = line_window(
                        result.content,
                        path=path,
                        start_line=start_line,
                        limit=limit,
                    )
                except (SecretFileError, BinaryContentError) as exc:
                    status = "blocked"
                    blocker = str(exc)
                    context.collector.file_summaries[-1] = context.collector.file_summaries[
                        -1
                    ].model_copy(
                        update={
                            "status": "blocked",
                            "blocker": blocker,
                        }
                    )
                else:
                    data.update(window.as_metadata())
                    data["content"] = window.content
                    capped = window.capped
                    blocker = blocker or None

            return _envelope(
                tool="read_file",
                status=status,
                policy=result.policy,
                data=data,
                summary=context.collector.file_summaries[-1].model_dump(
                    mode="json",
                    exclude_none=True,
                ),
                capped=capped,
                blocker=blocker,
            )

        def create_file(path: str, content: str) -> dict[str, Any]:
            """Create a workspace text file when policy allows it."""

            result = context.workspace_tools.create_file(
                path,
                content,
                approved_scope=context.automation_policy == "yolo"
                or context.approved_scope,
            )
            return _mutation_envelope("create_file", result, context)

        def update_file(path: str, content: str) -> dict[str, Any]:
            """Replace a workspace text file when policy allows it."""

            result = context.workspace_tools.update_file(
                path,
                content,
                approved_scope=context.automation_policy == "yolo"
                or context.approved_scope,
            )
            return _mutation_envelope("update_file", result, context)

        def delete_file(path: str) -> dict[str, Any]:
            """Delete a workspace file under approved or YOLO policy."""

            result = context.workspace_tools.delete_file(
                path,
                approved_scope=context.automation_policy == "yolo"
                or context.approved_scope,
                approved_delete=context.automation_policy == "yolo",
            )
            return _mutation_envelope("delete_file", result, context)

        def run_command(
            argv: list[str],
            purpose: str = "other",
            cwd: str = ".",
            timeout_seconds: float = 30.0,
        ) -> dict[str, Any]:
            """Run an argv command through SpeCode execution policy."""

            command = tuple(str(part) for part in argv)
            backend = context.execution_backend
            if context.automation_policy == "yolo" and _yolo_allows_command(command):
                backend = context.yolo_execution_backend or context.execution_backend

            result = backend.run_command(
                CommandRequest.from_argv(
                    command,
                    cwd=cwd,
                    timeout_seconds=timeout_seconds,
                    purpose=_command_purpose(purpose),
                    approved_scope=context.approved_scope,
                )
            )
            summary = summarize_command_result(result)
            context.collector.command_summaries.append(summary)
            stdout = sanitize_command_output(result.stdout)
            stderr = sanitize_command_output(result.stderr)
            return _envelope(
                tool="run_command",
                status=result.status,
                policy=result.policy,
                data={
                    "command": shlex.join(result.command),
                    "cwd": _display_path(result.cwd, context),
                    "exit_code": result.exit_code,
                    "stdout": stdout.text,
                    "stderr": stderr.text,
                    "timed_out": result.timed_out,
                    "redacted": stdout.redacted or stderr.redacted,
                },
                summary=summary.model_dump(mode="json", exclude_none=True),
                capped=stdout.capped or stderr.capped,
                blocker=result.blocker,
            )

        def web_search(
            query: str,
            max_results: int = MAX_WEB_RESULTS,
            allowed_domains: list[str] | None = None,
        ) -> dict[str, Any]:
            """Search the web through the configured controlled backend."""

            request = WebSearchRequest(
                query=query,
                max_results=max_results,
                allowed_domains=tuple(allowed_domains or ()),
            )
            response = context.web_search_backend.search(request)
            summary = WebSearchSummary(
                query=response.summary.query,
                status=response.summary.status,
                result_count=response.summary.result_count,
                sources=list(response.summary.urls),
                backend=response.summary.backend,
                blocker=response.summary.blocker,
            )
            context.collector.web_summaries.append(summary)
            return {
                "tool": "web_search",
                "status": response.status,
                "policy": {
                    "decision": "allow" if response.ok else "deny",
                    "reason": response.blocker or "Controlled web search completed.",
                    "required_approval": None,
                },
                "data": {
                    "query": response.query,
                    "results": [
                        {
                            "title": result.title,
                            "url": result.url,
                            "snippet": result.snippet,
                        }
                        for result in response.results
                    ],
                    "result_count": len(response.results),
                    "backend": response.backend,
                },
                "summary": summary.model_dump(mode="json", exclude_none=True),
                "capped": response.capped,
                "blocker": response.blocker,
            }

        return FunctionToolset(
            [
                list_files,
                search_files,
                read_file,
                create_file,
                update_file,
                delete_file,
                run_command,
                web_search,
            ],
            include_return_schema=True,
        )


def _mutation_envelope(
    tool: str,
    result: WorkspaceToolResult,
    context: RoleToolContext,
) -> dict[str, Any]:
    context.collector.file_summaries.append(_file_summary(result, context))
    summary = result.summary
    return _envelope(
        tool=tool,
        status=result.status,
        policy=result.policy,
        data={
            "path": _display_path(result.path, context),
            "action": getattr(summary, "action", None),
            "changed": getattr(summary, "changed", None),
            "bytes_written": getattr(summary, "bytes_written", None),
            "lines_written": getattr(summary, "lines_written", None),
        },
        summary=context.collector.file_summaries[-1].model_dump(
            mode="json",
            exclude_none=True,
        ),
        capped=False,
        blocker=result.blocker,
    )


def _file_summary(
    result: WorkspaceToolResult,
    context: RoleToolContext,
) -> FileOperationSummary:
    summary = summarize_file_operation(result)
    return summary.model_copy(update={"path": _display_path(summary.path, context)})


def _envelope(
    *,
    tool: str,
    status: str,
    policy: Any,
    data: dict[str, Any],
    summary: dict[str, Any],
    capped: bool,
    blocker: str | None,
) -> dict[str, Any]:
    return {
        "tool": tool,
        "status": status,
        "policy": {
            "decision": policy.decision,
            "reason": policy.reason,
            "required_approval": policy.required_approval,
        },
        "data": data,
        "summary": summary,
        "capped": capped,
        "blocker": blocker,
    }


def _display_path(path: str, context: RoleToolContext) -> str:
    try:
        return Path(path).resolve().relative_to(context.workspace_root).as_posix()
    except (OSError, ValueError):
        return str(path)


def _command_purpose(raw: str) -> Any:
    allowed = {"test", "lint", "build", "dev-server", "migration", "install", "other"}
    return raw if raw in allowed else "other"


def _yolo_allows_command(argv: Sequence[str]) -> bool:
    if not argv:
        return False
    executable = Path(argv[0]).name
    if executable in {"uv", "docker"}:
        return True
    return executable == "git" and len(argv) >= 2 and argv[1] == "status"
