from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import to_plain_text

from specode.cli import CommandRouter
from specode.interactive import (
    InteractiveShell,
    PromptConfig,
    PromptToolkitCompleter,
    create_prompt_session,
    is_exit_result,
    suggestion_to_completion,
)
from specode.runtime import ChatRequest, ChatResult, ChatRuntime


@dataclass(frozen=True)
class FakeSuggestion:
    label: str
    insert_text: str
    description: str
    kind: str
    replacement_start: int
    replacement_end: int


class RecordingCompletionEngine:
    def __init__(self, suggestions: list[Any]) -> None:
        self.suggestions = suggestions
        self.calls: list[tuple[str, int]] = []

    def complete(self, text: str, cursor_position: int) -> list[Any]:
        self.calls.append((text, cursor_position))
        return self.suggestions


class FakePromptSession:
    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self.prompts: list[str] = []

    def prompt(self, prompt_text: str) -> str:
        self.prompts.append(prompt_text)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


class FakeKind(str, Enum):
    CHAT = "chat"
    EXIT = "exit"


@dataclass(frozen=True)
class FakeRouteResult:
    kind: FakeKind
    text: str


class RecordingRouter:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def route(self, raw_input: str) -> FakeRouteResult:
        self.lines.append(raw_input)
        if raw_input == "/exit":
            return FakeRouteResult(FakeKind.EXIT, "Session ended.")
        return FakeRouteResult(FakeKind.CHAT, f"routed: {raw_input}")


class RecordingChatRuntime(ChatRuntime):
    def __init__(self) -> None:
        self.requests: list[ChatRequest] = []

    def run_chat(self, request: ChatRequest) -> ChatResult:
        self.requests.append(request)
        return ChatResult(text="chat response")


def test_completer_calls_engine_with_document_text_and_cursor() -> None:
    suggestion = FakeSuggestion(
        label="/steering",
        insert_text="/steering",
        description="Create missing/default steering docs",
        kind="command",
        replacement_start=0,
        replacement_end=3,
    )
    engine = RecordingCompletionEngine([suggestion])
    completer = PromptToolkitCompleter(engine)

    completions = list(
        completer.get_completions(Document("/st", cursor_position=3), object())
    )

    assert engine.calls == [("/st", 3)]
    assert len(completions) == 1
    completion = completions[0]
    assert completion.text == "/steering"
    assert completion.start_position == -3
    assert to_plain_text(completion.display) == "/steering"
    assert to_plain_text(completion.display_meta) == (
        "command - Create missing/default steering docs"
    )


def test_suggestion_mapping_converts_to_prompt_toolkit_completion() -> None:
    completion = suggestion_to_completion(
        {
            "label": "tasks/task.md",
            "insert_text": "tasks/task.md",
            "description": "workspace file",
            "kind": "file",
            "replacement_start": 6,
            "replacement_end": 10,
        },
        cursor_position=10,
    )

    assert completion.text == "tasks/task.md"
    assert completion.start_position == -4
    assert to_plain_text(completion.display) == "tasks/task.md"
    assert to_plain_text(completion.display_meta) == "file - workspace file"


def test_interactive_shell_routes_submitted_lines_until_exit() -> None:
    router = RecordingRouter()
    rendered: list[FakeRouteResult] = []
    session = FakePromptSession(["hello", "/exit"])
    shell = InteractiveShell(
        router,
        rendered.append,
        session=session,  # type: ignore[arg-type]
        prompt_config=PromptConfig(prompt_text="test> "),
    )

    shell.run()

    assert router.lines == ["hello", "/exit"]
    assert [result.text for result in rendered] == ["routed: hello", "Session ended."]
    assert session.prompts == ["test> ", "test> "]


def test_interactive_shell_stops_cleanly_on_eof() -> None:
    router = RecordingRouter()
    rendered: list[FakeRouteResult] = []
    shell = InteractiveShell(
        router,
        rendered.append,
        session=FakePromptSession([]),  # type: ignore[arg-type]
    )

    shell.run()

    assert router.lines == []
    assert rendered == []


def test_prompt_session_factory_installs_threaded_completer() -> None:
    session = create_prompt_session(RecordingCompletionEngine([]))

    assert session.completer is not None
    assert session.complete_while_typing is True


def test_reserved_prefix_submissions_still_go_through_router_not_chat(
    tmp_path: Path,
) -> None:
    chat_runtime = RecordingChatRuntime()
    router = CommandRouter(tmp_path, chat_runtime=chat_runtime)
    rendered: list[Any] = []
    shell = InteractiveShell(
        router,
        rendered.append,
        session=FakePromptSession(["@task.md", "/exit"]),  # type: ignore[arg-type]
    )

    shell.run()

    assert chat_runtime.requests == []
    assert rendered[0].kind.value == "reserved"
    assert rendered[1].kind.value == "exit"


def test_is_exit_result_accepts_string_enum_values() -> None:
    assert is_exit_result(FakeRouteResult(FakeKind.EXIT, "bye"))
    assert not is_exit_result(FakeRouteResult(FakeKind.CHAT, "hello"))
