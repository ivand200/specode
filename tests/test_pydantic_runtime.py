from __future__ import annotations

from pathlib import Path

from pydantic_ai.models.test import TestModel

from specode.pydantic_runtime import (
    DEFAULT_CHAT_MODEL,
    DEFAULT_OPENAI_REASONING_EFFORT,
    OpenAIChatRuntime,
    PydanticAgentRuntime,
    PydanticRuntimeConfig,
    RolePromptSpec,
)
from specode.runtime import ChatRequest
from specode.schemas import (
    CommandRunSummary,
    FileOperationSummary,
    RoleRunRequest,
    TaskReturn,
)


def test_pydantic_runtime_returns_role_run_result_with_valid_test_model() -> None:
    runtime = PydanticAgentRuntime(
        PydanticRuntimeConfig(
            model_override=TestModel(
                custom_output_args=_developer_payload(),
                call_tools=[],
            ),
        )
    )

    result = runtime.run_role(_developer_request())

    assert result.status == "completed"
    assert isinstance(result.role_return, TaskReturn)
    assert result.role_return.result == "ready_for_testing"


def test_pydantic_runtime_blocks_when_model_is_not_configured() -> None:
    runtime = PydanticAgentRuntime(PydanticRuntimeConfig(api_key=None))

    result = runtime.run_role(_developer_request())

    assert result.status == "blocked"
    assert "OPENAI_API_KEY" in (result.blocker or "")


def test_pydantic_runtime_reports_structured_output_validation_failures() -> None:
    runtime = PydanticAgentRuntime(
        PydanticRuntimeConfig(
            model_override=TestModel(
                custom_output_args={
                    "task": "Task 19",
                    "result": "ready_for_testing",
                    "contract_coverage": "wrong route",
                    "suggested_manager_action": "mark_blocked",
                },
                call_tools=[],
            ),
        )
    )

    result = runtime.run_role(_developer_request())

    assert result.status == "blocked"
    assert "structured output validation failed" in (result.blocker or "")


def test_pydantic_runtime_uses_prompt_loader_hook() -> None:
    loader = RecordingPromptLoader()
    runtime = PydanticAgentRuntime(
        PydanticRuntimeConfig(
            model_override=TestModel(
                custom_output_args=_developer_payload(),
                call_tools=[],
            ),
        ),
        prompt_loader=loader,
    )

    result = runtime.run_role(_developer_request())

    assert result.status == "completed"
    assert loader.requests == ["specode-v0-cli-agent"]


def test_pydantic_runtime_preserves_tool_and_backend_summaries() -> None:
    command_summary = CommandRunSummary(
        command="uv run pytest tests/test_pydantic_runtime.py",
        status="ok",
        exit_code=0,
        purpose="test",
    )
    file_summary = FileOperationSummary(
        operation="update_file",
        path="src/specode/pydantic_runtime.py",
        status="blocked",
        action="updated",
        changed=False,
        blocker="read-only policy blocked mutation",
    )
    runtime = PydanticAgentRuntime(
        PydanticRuntimeConfig(
            model_override=TestModel(
                custom_output_args=_developer_payload(),
                call_tools=[],
            ),
        )
    )

    result = runtime.run_role(
        _developer_request(
            command_summaries=[command_summary],
            file_summaries=[file_summary],
        )
    )

    assert result.command_summaries == [command_summary]
    assert result.file_summaries == [file_summary]


def test_pydantic_runtime_config_uses_openai_env_contract(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SPECODE_MODEL", "legacy-model")
    monkeypatch.setenv("SPECODE_MODEL_PROVIDER", "legacy-provider")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("CHAT_MODEL", "gpt-test")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")

    config = PydanticRuntimeConfig.from_env()

    assert config.chat_model == "gpt-test"
    assert config.api_key == "sk-test"
    assert config.base_url == "https://example.test/v1"
    assert config.reasoning_effort == "high"
    assert config.model_settings()["openai_reasoning_effort"] == "high"


def test_pydantic_runtime_config_defaults_openai_chat_values(monkeypatch) -> None:
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)

    config = PydanticRuntimeConfig.from_env()

    assert config.chat_model == DEFAULT_CHAT_MODEL
    assert config.reasoning_effort == DEFAULT_OPENAI_REASONING_EFFORT


def test_pydantic_runtime_config_can_prime_environment_from_dotenv(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "OPENAI_API_KEY='sk-dotenv'\nCHAT_MODEL=gpt-dotenv\n",
        encoding="utf-8",
    )

    config = PydanticRuntimeConfig.from_env(dotenv_path=dotenv)

    assert config.api_key == "sk-dotenv"
    assert config.chat_model == "gpt-dotenv"


def test_pydantic_runtime_dotenv_does_not_override_process_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-process")
    dotenv = tmp_path / ".env"
    dotenv.write_text("OPENAI_API_KEY=sk-dotenv\n", encoding="utf-8")

    config = PydanticRuntimeConfig.from_env(dotenv_path=dotenv)

    assert config.api_key == "sk-process"


def test_pydantic_runtime_ignores_legacy_model_env_vars(monkeypatch) -> None:
    monkeypatch.delenv("CHAT_MODEL", raising=False)
    monkeypatch.setenv("SPECODE_MODEL", "legacy-model")
    monkeypatch.setenv("SPECODE_MODEL_PROVIDER", "legacy-provider")

    config = PydanticRuntimeConfig.from_env()

    assert config.chat_model == DEFAULT_CHAT_MODEL


def test_pydantic_runtime_blocks_invalid_reasoning_effort() -> None:
    runtime = PydanticAgentRuntime(
        PydanticRuntimeConfig(
            api_key="sk-test",
            reasoning_effort="maximum",
        )
    )

    result = runtime.run_role(_developer_request())

    assert result.status == "blocked"
    assert "OPENAI_REASONING_EFFORT" in (result.blocker or "")


def test_openai_chat_runtime_uses_mocked_text_model() -> None:
    runtime = OpenAIChatRuntime(
        PydanticRuntimeConfig(
            model_override=TestModel(custom_output_text="mocked chat response"),
        )
    )

    result = runtime.run_chat(ChatRequest(message="explain the project"))

    assert result.status == "completed"
    assert result.text == "mocked chat response"


def test_openai_chat_runtime_blocks_when_api_key_is_missing() -> None:
    runtime = OpenAIChatRuntime(PydanticRuntimeConfig(api_key=None))

    result = runtime.run_chat(ChatRequest(message="hello"))

    assert result.status == "blocked"
    assert "OPENAI_API_KEY" in result.text


class RecordingPromptLoader:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def load(self, request: RoleRunRequest) -> RolePromptSpec:
        self.requests.append(request.task_name)
        return RolePromptSpec(
            instructions="Use the injected role spec.",
            prompt="Return the developer payload.",
        )


def _developer_request(
    *,
    command_summaries: list[CommandRunSummary] | None = None,
    file_summaries: list[FileOperationSummary] | None = None,
) -> RoleRunRequest:
    return RoleRunRequest(
        task_name="specode-v0-cli-agent",
        role="developer",
        task="Task 19: PydanticAgentRuntime integration boundary.",
        instructions="Preserve ToolPolicy and ExecutionBackend boundaries.",
        approved_scope=True,
        artifact_paths={"task": str(Path("tasks/specode-v0-cli-agent/task.md"))},
        command_summaries=command_summaries or [],
        file_summaries=file_summaries or [],
    )


def _developer_payload() -> dict[str, object]:
    return {
        "task": "Task 19: PydanticAgentRuntime integration boundary.",
        "result": "ready_for_testing",
        "files_changed": ["src/specode/pydantic_runtime.py"],
        "checks_run": ["uv run pytest tests/test_pydantic_runtime.py"],
        "interface_impact": "internal-only",
        "contract_coverage": "Pydantic runtime contract tests exercise the adapter.",
        "suggested_split": None,
        "suggested_manager_action": "run_tester",
        "blocker": None,
        "notes": [],
    }
