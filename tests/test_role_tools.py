from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from specode.execution import CommandRequest, CommandResult, ExecutionBackend
from specode.policy import PolicyDecision, ToolPolicy
from specode.role_tools import RoleToolContext, RoleToolsetFactory
from specode.schemas import RoleRunRequest
from specode.web_search import FakeWebSearchBackend, WebSearchResult
from specode.workspace_tools import WorkspaceTools


def test_role_toolset_exposes_approved_tool_names(tmp_path: Path) -> None:
    context = _context(tmp_path)

    toolset = RoleToolsetFactory().build(context)

    assert sorted(toolset.tools) == [
        "create_file",
        "delete_file",
        "list_files",
        "read_file",
        "run_command",
        "search_files",
        "update_file",
        "web_search",
    ]


def test_read_file_returns_line_window_and_sanitizes_secret_lines(tmp_path: Path) -> None:
    target = tmp_path / "sample.txt"
    target.write_text("safe\napi_key = nope\nthird\n", encoding="utf-8")
    context = _context(tmp_path)
    tool = RoleToolsetFactory().build(context).tools["read_file"].function

    result = tool("sample.txt", start_line=1, limit=3)

    assert result["status"] == "ok"
    assert "nope" not in result["data"]["content"]
    assert result["data"]["redacted"]
    assert result["data"]["total_lines"] == 3
    assert context.collector.file_summaries[-1].operation == "read_file"


def test_secret_env_read_is_blocked_before_content_reaches_model(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-test\n", encoding="utf-8")
    context = _context(tmp_path)
    tool = RoleToolsetFactory().build(context).tools["read_file"].function

    result = tool(".env")

    assert result["status"] == "blocked"
    assert "sk-test" not in str(result)
    assert context.collector.file_summaries[-1].status == "blocked"


def test_delete_file_is_blocked_under_approved_and_allowed_under_yolo(
    tmp_path: Path,
) -> None:
    (tmp_path / "approved.txt").write_text("keep", encoding="utf-8")
    approved = _context(tmp_path, automation_policy="approved")
    approved_delete = RoleToolsetFactory().build(approved).tools["delete_file"].function

    approved_result = approved_delete("approved.txt")

    assert approved_result["status"] == "blocked"
    assert (tmp_path / "approved.txt").exists()

    (tmp_path / "yolo.txt").write_text("delete", encoding="utf-8")
    yolo = _context(tmp_path, automation_policy="yolo", approved_scope=False)
    yolo_delete = RoleToolsetFactory().build(yolo).tools["delete_file"].function

    yolo_result = yolo_delete("yolo.txt")

    assert yolo_result["status"] == "ok"
    assert not (tmp_path / "yolo.txt").exists()


def test_yolo_create_file_allows_workspace_mutation_even_without_approved_scope(
    tmp_path: Path,
) -> None:
    context = _context(tmp_path, automation_policy="yolo", approved_scope=False)
    create_file = RoleToolsetFactory().build(context).tools["create_file"].function

    result = create_file("created.txt", "hello\n")

    assert result["status"] == "ok"
    assert (tmp_path / "created.txt").read_text(encoding="utf-8") == "hello\n"


def test_yolo_command_allowlist_uses_yolo_backend(tmp_path: Path) -> None:
    normal = RecordingBackend("normal")
    yolo = RecordingBackend("yolo")
    context = _context(
        tmp_path,
        automation_policy="yolo",
        execution_backend=normal,
        yolo_execution_backend=yolo,
    )
    run_command = RoleToolsetFactory().build(context).tools["run_command"].function

    result = run_command(["uv", "sync"], purpose="install")

    assert result["status"] == "ok"
    assert normal.requests == []
    assert yolo.requests[0].argv == ("uv", "sync")
    assert context.collector.command_summaries[-1].command == "uv sync"


def test_web_search_uses_controlled_backend_and_collects_summary(
    tmp_path: Path,
) -> None:
    backend = FakeWebSearchBackend(
        {
            "pydantic tools": [
                WebSearchResult(
                    title="Pydantic AI tools",
                    url="https://docs.example/tools",
                    snippet="Function tools documentation.",
                )
            ]
        }
    )
    context = _context(tmp_path, web_search_backend=backend)
    web_search = RoleToolsetFactory().build(context).tools["web_search"].function

    result = web_search("pydantic tools")

    assert result["status"] == "ok"
    assert result["data"]["results"][0]["url"] == "https://docs.example/tools"
    assert context.collector.web_summaries[-1].query == "pydantic tools"
    assert context.collector.web_summaries[-1].sources == [
        "https://docs.example/tools"
    ]


def _context(
    workspace_root: Path,
    *,
    automation_policy: str = "approved",
    approved_scope: bool = True,
    execution_backend: ExecutionBackend | None = None,
    yolo_execution_backend: ExecutionBackend | None = None,
    web_search_backend: FakeWebSearchBackend | None = None,
) -> RoleToolContext:
    request = RoleRunRequest(
        task_name="role-tools",
        role="developer",
        task="Tool task.",
        approved_scope=approved_scope,
        automation_policy=automation_policy,  # type: ignore[arg-type]
    )
    policy = ToolPolicy.workspace_write(workspace_root=workspace_root)
    return RoleToolContext(
        request=request,
        workspace_root=workspace_root.resolve(),
        workspace_tools=WorkspaceTools(workspace_root, policy=policy),
        execution_backend=execution_backend or RecordingBackend("normal"),
        yolo_execution_backend=yolo_execution_backend or RecordingBackend("yolo"),
        web_search_backend=web_search_backend or FakeWebSearchBackend(),
    )


class RecordingBackend(ExecutionBackend):
    def __init__(self, name: str) -> None:
        self.name = name
        self.requests: list[CommandRequest] = []

    def run_command(self, request: CommandRequest) -> CommandResult:
        self.requests.append(request)
        now = datetime(2026, 5, 4, tzinfo=UTC)
        return CommandResult(
            command=request.argv,
            cwd=str(request.cwd or "."),
            status="ok",
            exit_code=0,
            stdout=f"{self.name} stdout\n",
            stderr="",
            timed_out=False,
            started_at=now,
            ended_at=now,
            timeout_seconds=request.timeout_seconds,
            purpose=request.purpose,
            policy=PolicyDecision(
                operation="command",
                mode="full-access",
                decision="allow",
                reason=f"{self.name} allowed",
                command=request.argv,
                cwd=str(request.cwd or "."),
                purpose=request.purpose,
            ),
        )
