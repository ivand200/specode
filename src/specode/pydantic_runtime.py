"""Pydantic AI adapter for the SpeCode AgentRuntime boundary."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ValidationError
from pydantic_ai import Agent, UnexpectedModelBehavior
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from pydantic_ai.providers.openai import OpenAIProvider

from specode.references import PYDANTIC_AI_REFERENCES, ROLE_RUNTIME_INSTRUCTIONS
from specode.runtime import (
    AgentRuntime,
    ChatRequest,
    ChatResult,
    ChatRuntime,
    blocked_role_return_payload,
    role_return_model,
)
from specode.role_tools import RoleToolContext, RoleToolsetFactory
from specode.schemas import (
    RoleName,
    RoleRunRequest,
    RoleRunResult,
    parse_role_return,
)
from specode.web_search import WebSearchBackend


DEFAULT_CHAT_MODEL = "gpt-5.4-mini"
DEFAULT_OPENAI_REASONING_EFFORT = "xhigh"
OpenAIReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
SUPPORTED_OPENAI_REASONING_EFFORTS: frozenset[str] = frozenset(
    {"none", "minimal", "low", "medium", "high", "xhigh"}
)


class RolePromptLoader(Protocol):
    """Hook for building role instructions and prompts before model execution."""

    def load(self, request: RoleRunRequest) -> "RolePromptSpec":
        """Return the instructions and user prompt for one role run."""


@dataclass(frozen=True)
class RolePromptSpec:
    """Resolved prompt material for a Pydantic AI role run."""

    instructions: str
    prompt: str
    reference_titles: tuple[str, ...] = ()


@dataclass(frozen=True)
class PydanticRuntimeConfig:
    """Configuration for the OpenAI ChatGPT runtime adapter."""

    chat_model: str = DEFAULT_CHAT_MODEL
    api_key: str | None = None
    base_url: str | None = None
    reasoning_effort: str = DEFAULT_OPENAI_REASONING_EFFORT
    retries: int = 1
    output_retries: int | None = None
    role_spec_dir: Path | str | None = None
    workspace_root: Path | str | None = None
    agent_name_prefix: str = "specode"
    model_override: Any | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "chat_model",
            self.chat_model.strip() if isinstance(self.chat_model, str) else self.chat_model,
        )
        if not self.chat_model:
            object.__setattr__(self, "chat_model", DEFAULT_CHAT_MODEL)

        object.__setattr__(self, "api_key", _non_empty(self.api_key))
        object.__setattr__(self, "base_url", _non_empty(self.base_url))
        object.__setattr__(
            self,
            "reasoning_effort",
            self.reasoning_effort.strip().lower()
            if isinstance(self.reasoning_effort, str)
            else self.reasoning_effort,
        )
        if not self.reasoning_effort:
            object.__setattr__(
                self,
                "reasoning_effort",
                DEFAULT_OPENAI_REASONING_EFFORT,
            )
        if self.workspace_root is not None:
            object.__setattr__(self, "workspace_root", Path(self.workspace_root))

    @classmethod
    def from_env(
        cls,
        *,
        dotenv_path: Path | str | None = None,
    ) -> "PydanticRuntimeConfig":
        """Load OpenAI chat settings from environment, optionally priming from .env."""

        if dotenv_path is not None:
            load_env_file(dotenv_path)

        role_spec_dir = os.environ.get("SPECODE_ROLE_SPEC_DIR")
        return cls(
            chat_model=os.environ.get("CHAT_MODEL") or DEFAULT_CHAT_MODEL,
            api_key=os.environ.get("OPENAI_API_KEY"),
            base_url=os.environ.get("OPENAI_BASE_URL"),
            reasoning_effort=(
                os.environ.get("OPENAI_REASONING_EFFORT")
                or DEFAULT_OPENAI_REASONING_EFFORT
            ),
            role_spec_dir=Path(role_spec_dir) if role_spec_dir else None,
        )

    def configuration_blocker(self) -> str | None:
        """Return a sanitized blocker for invalid or incomplete live config."""

        if self.reasoning_effort not in SUPPORTED_OPENAI_REASONING_EFFORTS:
            return (
                "OpenAI runtime blocked: OPENAI_REASONING_EFFORT must be one of "
                f"{', '.join(sorted(SUPPORTED_OPENAI_REASONING_EFFORTS))}."
            )
        if self.model_override is None and self.api_key is None:
            return "OpenAI runtime blocked: OPENAI_API_KEY is not configured."
        return None

    def model_settings(self) -> OpenAIChatModelSettings:
        """Return model settings for OpenAI-specific request parameters."""

        return OpenAIChatModelSettings(
            openai_reasoning_effort=self.reasoning_effort,  # type: ignore[typeddict-item]
        )

    def openai_chat_model(self) -> OpenAIChatModel:
        """Build the configured OpenAI-compatible chat model."""

        provider = OpenAIProvider(api_key=self.api_key, base_url=self.base_url)
        return OpenAIChatModel(
            self.chat_model,
            provider=provider,
            settings=self.model_settings(),
        )


@dataclass
class DefaultRolePromptLoader:
    """Load compact role prompts and optional repo-local role specs."""

    role_spec_dir: Path | str | None = None
    max_artifact_chars: int = 20_000
    _role_spec_cache: dict[RoleName, str] = field(default_factory=dict, init=False)

    def load(self, request: RoleRunRequest) -> RolePromptSpec:
        instructions = [
            ROLE_RUNTIME_INSTRUCTIONS[request.role],
            request.instructions.strip(),
            self._role_spec(request.role).strip(),
            _reference_facts(),
        ]
        prompt = "\n\n".join(
            part
            for part in (
                f"Task name: {request.task_name}",
                f"Role: {request.role}",
                f"Approved scope: {request.approved_scope}",
                "Task artifact:\n" + request.task,
                self._artifact_context(request.artifact_paths),
                _summary_context(request),
            )
            if part.strip()
        )
        return RolePromptSpec(
            instructions="\n\n".join(part for part in instructions if part),
            prompt=prompt,
            reference_titles=tuple(ref.title for ref in PYDANTIC_AI_REFERENCES),
        )

    def _role_spec(self, role: RoleName) -> str:
        if role in self._role_spec_cache:
            return self._role_spec_cache[role]
        if self.role_spec_dir is None:
            self._role_spec_cache[role] = ""
            return ""

        base = Path(self.role_spec_dir)
        for suffix in (".md", ".txt"):
            path = base / f"{role}{suffix}"
            if path.exists() and path.is_file():
                text = path.read_text(encoding="utf-8")
                self._role_spec_cache[role] = text[: self.max_artifact_chars]
                return self._role_spec_cache[role]

        self._role_spec_cache[role] = ""
        return ""

    def _artifact_context(self, artifact_paths: dict[str, str]) -> str:
        chunks: list[str] = []
        remaining = self.max_artifact_chars
        for name, raw_path in sorted(artifact_paths.items()):
            if remaining <= 0:
                break
            path = Path(raw_path)
            if not path.exists() or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")[:remaining]
            remaining -= len(text)
            chunks.append(f"{name} artifact ({path.name}):\n{text}")
        if not chunks:
            return ""
        return "Approved artifact context:\n\n" + "\n\n".join(chunks)


class PydanticAgentRuntime(AgentRuntime):
    """Thin Pydantic AI adapter behind SpeCode's AgentRuntime interface.

    The adapter constructs an Agent with the role-specific structured
    ``output_type`` and validates the final output again through SpeCode's role
    schemas. It does not expose filesystem or shell tools; those remain owned
    by ToolPolicy, WorkspaceTools, and ExecutionBackend.
    """

    def __init__(
        self,
        config: PydanticRuntimeConfig | None = None,
        *,
        prompt_loader: RolePromptLoader | None = None,
        toolset_factory: RoleToolsetFactory | None = None,
        web_search_backend: WebSearchBackend | None = None,
    ) -> None:
        self.config = config or PydanticRuntimeConfig.from_env()
        self.prompt_loader = prompt_loader or DefaultRolePromptLoader(
            self.config.role_spec_dir
        )
        self.toolset_factory = toolset_factory or RoleToolsetFactory()
        self.web_search_backend = web_search_backend

    def run_role(self, request: RoleRunRequest) -> RoleRunResult:
        validated_request = RoleRunRequest.model_validate(request)
        blocker = self.config.configuration_blocker()
        if blocker is not None:
            return self._blocked_result(
                validated_request,
                blocker,
            )

        try:
            prompt_spec = self.prompt_loader.load(validated_request)
            model = (
                "test"
                if self.config.model_override is not None
                else self.config.openai_chat_model()
            )
            agent = self._agent_for(validated_request.role, prompt_spec, model)
            tool_context = self._tool_context(validated_request)
            toolsets = [self.toolset_factory.build(tool_context)]
            if self.config.model_override is None:
                run_result = agent.run_sync(prompt_spec.prompt, toolsets=toolsets)
            else:
                with agent.override(model=self.config.model_override):
                    run_result = agent.run_sync(prompt_spec.prompt, toolsets=toolsets)
            role_return = parse_role_return(
                validated_request.role,
                _output_payload(run_result.output),
            )
        except (UnexpectedModelBehavior, ValidationError) as exc:
            return self._blocked_result(
                validated_request,
                f"Pydantic structured output validation failed: {exc}",
            )
        except Exception as exc:
            return self._blocked_result(
                validated_request,
                f"Pydantic role run failed: {type(exc).__name__}: {exc}",
            )

        status = "blocked" if role_return.result == "blocked" else "completed"
        return RoleRunResult(
            task_name=validated_request.task_name,
            role=validated_request.role,
            status=status,
            role_return=role_return,
            command_summaries=[
                *validated_request.command_summaries,
                *tool_context.collector.command_summaries,
            ],
            file_summaries=[
                *validated_request.file_summaries,
                *tool_context.collector.file_summaries,
            ],
            web_summaries=[
                *validated_request.web_summaries,
                *tool_context.collector.web_summaries,
            ],
            blocker=getattr(role_return, "blocker", None),
        )

    def _agent_for(
        self,
        role: RoleName,
        prompt_spec: RolePromptSpec,
        model: Any | None,
    ) -> Agent[Any, Any]:
        return Agent(
            model,
            name=f"{self.config.agent_name_prefix}-{role}",
            instructions=prompt_spec.instructions,
            output_type=role_return_model(role),
            retries=self.config.retries,
            output_retries=self.config.output_retries,
            defer_model_check=True,
        )

    def _tool_context(self, request: RoleRunRequest) -> RoleToolContext:
        return RoleToolContext.default(
            request,
            workspace_root=self._workspace_root(request),
            web_search_backend=self.web_search_backend,
        )

    def _workspace_root(self, request: RoleRunRequest) -> Path:
        if self.config.workspace_root is not None:
            return Path(self.config.workspace_root).resolve()
        task_path = request.artifact_paths.get("task")
        if task_path is not None:
            path = Path(task_path).resolve()
            parts = path.parts
            if "tasks" in parts:
                tasks_index = parts.index("tasks")
                if tasks_index > 0:
                    return Path(*parts[:tasks_index]).resolve()
        return Path.cwd().resolve()

    def _blocked_result(
        self,
        request: RoleRunRequest,
        blocker: str,
    ) -> RoleRunResult:
        role_return = parse_role_return(
            request.role,
            blocked_role_return_payload(request, blocker),
        )
        return RoleRunResult(
            task_name=request.task_name,
            role=request.role,
            status="blocked",
            role_return=role_return,
            command_summaries=request.command_summaries,
            file_summaries=request.file_summaries,
            web_summaries=request.web_summaries,
            blocker=blocker,
        )


class OpenAIChatRuntime(ChatRuntime):
    """OpenAI-backed runtime for ordinary non-command chat input."""

    def __init__(self, config: PydanticRuntimeConfig | None = None) -> None:
        self.config = config or PydanticRuntimeConfig.from_env()

    def run_chat(self, request: ChatRequest) -> ChatResult:
        blocker = self.config.configuration_blocker()
        if blocker is not None:
            return ChatResult(text=blocker, status="blocked", blocker=blocker)

        instructions = (
            "You are SpeCode's normal coding assistant. Answer the user's prompt. "
            "Do not imply that /spec artifacts were created. Do not read .env or "
            "reveal secrets."
        )
        try:
            model = (
                "test"
                if self.config.model_override is not None
                else self.config.openai_chat_model()
            )
            agent = Agent(
                model,
                name=f"{self.config.agent_name_prefix}-chat",
                instructions=instructions,
                output_type=str,
                retries=self.config.retries,
                output_retries=self.config.output_retries,
                defer_model_check=True,
            )
            if self.config.model_override is None:
                run_result = agent.run_sync(request.message)
            else:
                with agent.override(model=self.config.model_override):
                    run_result = agent.run_sync(request.message)
        except Exception as exc:
            blocker = f"OpenAI chat failed: {type(exc).__name__}: {exc}"
            return ChatResult(text=blocker, status="blocked", blocker=blocker)

        return ChatResult(text=str(run_result.output))


def _output_payload(output: object) -> object:
    if isinstance(output, BaseModel):
        return output.model_dump(mode="json")
    return output


def _non_empty(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def load_env_file(path: Path | str) -> None:
    """Load simple KEY=VALUE pairs into ``os.environ`` without overriding values."""

    env_path = Path(path)
    if not env_path.exists() or not env_path.is_file():
        return

    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return

    for raw_line in lines:
        parsed = _parse_env_line(raw_line)
        if parsed is None:
            continue
        key, value = parsed
        os.environ.setdefault(key, value)


def _parse_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or "=" not in line:
        return None
    if line.startswith("export "):
        line = line[len("export ") :].lstrip()

    key, value = line.split("=", 1)
    key = key.strip()
    if not key or not key.replace("_", "").isalnum() or key[0].isdigit():
        return None

    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def _reference_facts() -> str:
    return "Runtime reference facts:\n" + "\n".join(
        f"- {ref.title}: {ref.fact}" for ref in PYDANTIC_AI_REFERENCES
    )


def _summary_context(request: RoleRunRequest) -> str:
    sections: list[str] = []
    if request.command_summaries:
        commands = "\n".join(
            f"- {summary.command}: {summary.status}" for summary in request.command_summaries
        )
        sections.append("Command summaries:\n" + commands)
    if request.file_summaries:
        files = "\n".join(
            f"- {summary.operation} {summary.path}: {summary.status}"
            for summary in request.file_summaries
        )
        sections.append("File operation summaries:\n" + files)
    return "\n\n".join(sections)
