from __future__ import annotations

import json
from pathlib import Path

from pydantic_ai.models.test import TestModel

from specode.artifacts import ArtifactStore
from specode.pydantic_runtime import (
    OpenAIChatRuntime,
    PydanticAgentRuntime,
    PydanticRuntimeConfig,
)
from specode.run_store import RunStore
from specode.runtime import AgentRuntime, ChatRequest
from specode.schemas import (
    ArtifactStatuses,
    ReviewReturn,
    RoleRunRequest,
    RoleRunResult,
    TaskReturn,
    ValidationReturn,
    WorkflowState,
)
from specode.web_search import FakeWebSearchBackend, WebSearchResult
from specode.workflow import WorkflowEngine


FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "openai_chatgpt_runtime"


def test_openai_chatgpt_runtime_e2e_uses_mocked_chat_and_role_responses(
    tmp_path: Path,
) -> None:
    chat_fixture = _read_json("chat_response.json")
    role_fixtures = _read_json("role_returns.json")
    store = _approved_store(tmp_path, "openai-runtime-e2e")

    chat = OpenAIChatRuntime(
        PydanticRuntimeConfig(
            model_override=TestModel(custom_output_text=chat_fixture["text"]),
        )
    )
    chat_result = chat.run_chat(ChatRequest(message="explain the current task"))

    pipeline = WorkflowEngine(store).run_role_pipeline(
        "openai-runtime-e2e",
        runtime=ScriptedPydanticRuntime(role_fixtures),
    )
    runs = RunStore(store).list_runs("openai-runtime-e2e")

    assert chat_result.status == "completed"
    assert chat_result.text == chat_fixture["text"]
    assert pipeline.done
    assert [record.role for record in runs] == ["developer", "tester", "reviewer"]
    assert runs[0].role_return["result"] == "ready_for_testing"
    assert runs[1].role_return["result"] == "pass"
    assert runs[2].role_return["result"] == "pass"
    assert _serialized(runs).find("OPENAI_API_KEY") == -1
    assert _serialized(runs).find("sk-") == -1
    assert _serialized(runs).find("raw transcript") == -1


def test_openai_chatgpt_runtime_e2e_blocks_malformed_mocked_response(
    tmp_path: Path,
) -> None:
    role_fixtures = _read_json("role_returns.json")
    store = _approved_store(tmp_path, "malformed-openai-runtime-e2e")
    runtime = ScriptedPydanticRuntime(
        {
            "developer": role_fixtures["malformed_developer"],
            "tester": role_fixtures["tester"],
            "reviewer": role_fixtures["reviewer"],
        }
    )

    result = WorkflowEngine(store).run_role_pipeline(
        "malformed-openai-runtime-e2e",
        runtime=runtime,
    )
    runs = RunStore(store).list_runs("malformed-openai-runtime-e2e")

    assert result.blocked
    assert result.state.current_stage == "implementation"
    assert [record.role for record in runs] == ["developer"]
    assert runs[0].status == "blocked"
    assert "structured output validation failed" in (runs[0].blocker or "")


def test_openai_chatgpt_runtime_e2e_records_controlled_web_search_tool(
    tmp_path: Path,
) -> None:
    role_fixtures = _read_json("role_returns.json")
    store = _approved_store(tmp_path, "web-search-tool-e2e")
    runtime = WebSearchToolRuntime(role_fixtures, workspace_root=tmp_path)

    result = WorkflowEngine(store).run_role_pipeline(
        "web-search-tool-e2e",
        runtime=runtime,
    )
    runs = RunStore(store).list_runs("web-search-tool-e2e")

    assert result.done
    assert runs[0].role == "developer"
    assert runs[0].web_searches[0].kind == "web_search"
    assert runs[0].web_searches[0].query == "a"
    assert runs[0].web_searches[0].sources == ["https://docs.example/web-search"]
    assert _serialized(runs).find("deterministic snippet") == -1


def test_saved_role_schema_summary_matches_current_pydantic_models() -> None:
    saved = _read_json("role_schema_summary.json")

    assert saved["developer"] == _schema_summary(TaskReturn)
    assert saved["tester"] == _schema_summary(ValidationReturn)
    assert saved["reviewer"] == _schema_summary(ReviewReturn)


class ScriptedPydanticRuntime(AgentRuntime):
    def __init__(self, role_fixtures: dict[str, object]) -> None:
        self.role_fixtures = role_fixtures

    def run_role(self, request: RoleRunRequest) -> RoleRunResult:
        payload = self.role_fixtures[request.role]
        runtime = PydanticAgentRuntime(
            PydanticRuntimeConfig(
                model_override=TestModel(custom_output_args=payload, call_tools=[]),
            )
        )
        return runtime.run_role(request)


class WebSearchToolRuntime(AgentRuntime):
    def __init__(self, role_fixtures: dict[str, object], *, workspace_root: Path) -> None:
        self.role_fixtures = role_fixtures
        self.workspace_root = workspace_root
        self.web_search_backend = FakeWebSearchBackend(
            {
                "a": [
                    WebSearchResult(
                        title="Controlled web search",
                        url="https://docs.example/web-search",
                        snippet="deterministic snippet",
                    )
                ]
            }
        )

    def run_role(self, request: RoleRunRequest) -> RoleRunResult:
        payload = self.role_fixtures[request.role]
        call_tools: list[str] = ["web_search"] if request.role == "developer" else []
        runtime = PydanticAgentRuntime(
            PydanticRuntimeConfig(
                model_override=TestModel(
                    custom_output_args=payload,
                    call_tools=call_tools,
                ),
                workspace_root=self.workspace_root,
            ),
            web_search_backend=self.web_search_backend,
        )
        return runtime.run_role(request)


def _approved_store(workspace: Path, task_name: str) -> ArtifactStore:
    store = ArtifactStore(workspace)
    store.write_task_text(task_name, "task.md", "# Task\n\nOpenAI runtime E2E.\n")
    store.write_task_text(task_name, "design.md", "# Design\n\nApproved.\n")
    store.write_task_text(task_name, "tasks.md", "# Tasks\n\n- Run mocked runtime.\n")
    store.save_task_state(
        WorkflowState(
            task_name=task_name,
            task_type="feature",
            current_stage="implementation",
            status="approved",
            artifacts=ArtifactStatuses(
                task="approved",
                research="skipped",
                decision="approved",
                tasks="approved",
            ),
        )
    )
    return store


def _schema_summary(
    model: type[TaskReturn] | type[ValidationReturn] | type[ReviewReturn],
) -> dict[str, object]:
    schema = model.model_json_schema()
    result_property = schema["properties"]["result"]
    action_property = schema["properties"]["suggested_manager_action"]
    return {
        "model": model.__name__,
        "required": schema["required"],
        "result_values": result_property["enum"],
        "manager_actions": action_property["enum"],
    }


def _read_json(filename: str) -> dict[str, object]:
    return json.loads(FIXTURE_DIR.joinpath(filename).read_text(encoding="utf-8"))


def _serialized(value: object) -> str:
    return json.dumps(
        value,
        default=lambda item: item.model_dump(mode="json"),
        sort_keys=True,
    )
