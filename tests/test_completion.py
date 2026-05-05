from __future__ import annotations

from dataclasses import dataclass

from specode.completion import (
    CompletionMode,
    FileCandidate,
    SuggestionKind,
    complete,
    detect_completion_context,
)


@dataclass(frozen=True)
class Command:
    name: str
    description: str
    aliases: tuple[str, ...] = ()
    hidden: bool = False


class Catalog:
    def __init__(self, commands: tuple[Command, ...]) -> None:
        self._commands = commands

    def visible_commands(self) -> tuple[Command, ...]:
        return tuple(command for command in self._commands if not command.hidden)


CATALOG = Catalog(
    (
        Command("spec", "Create or continue a spec workflow."),
        Command("steering", "Create or update steering documents."),
        Command("status", "Show current workflow status."),
        Command("exit", "Leave SpeCode.", aliases=("quit",)),
        Command("debug", "Internal diagnostic command.", hidden=True),
    )
)


def labels(suggestions: tuple) -> tuple[str, ...]:
    return tuple(suggestion.label for suggestion in suggestions)


def test_slash_root_suggests_visible_commands() -> None:
    suggestions = complete("/", catalog=CATALOG)

    assert labels(suggestions) == ("/spec", "/steering", "/status", "/exit")
    assert all(suggestion.kind == SuggestionKind.COMMAND for suggestion in suggestions)


def test_slash_prefix_filters_commands_and_replaces_active_token() -> None:
    suggestions = complete("/st", catalog=CATALOG)

    assert labels(suggestions) == ("/steering", "/status")
    assert {
        (suggestion.replacement_start, suggestion.replacement_end)
        for suggestion in suggestions
    } == {(0, 3)}


def test_unknown_slash_prefix_returns_no_suggestions() -> None:
    assert complete("/dance", catalog=CATALOG) == ()


def test_file_reference_suggests_workspace_relative_paths() -> None:
    suggestions = complete(
        "@steering",
        file_candidates=(
            FileCandidate("steering/", is_directory=True),
            "steering/product.md",
            "tasks/specode-v0-cli-agent/task.md",
        ),
    )

    assert labels(suggestions) == ("steering/", "steering/product.md")
    assert suggestions[0].kind == SuggestionKind.DIRECTORY
    assert suggestions[1].kind == SuggestionKind.FILE


def test_file_reference_context_wins_after_slash_command() -> None:
    context = detect_completion_context("/spec @task")
    suggestions = complete(
        "/spec @task",
        catalog=CATALOG,
        file_candidates=(
            FileCandidate("tasks/", is_directory=True),
            "tasks/specode-v0-cli-agent/task.md",
        ),
    )

    assert context.mode == CompletionMode.FILE
    assert labels(suggestions) == ("tasks/", "tasks/specode-v0-cli-agent/task.md")


def test_file_reference_supports_escaped_spaces() -> None:
    suggestions = complete(
        "@docs/my\\ file",
        file_candidates=("docs/my file.md", "docs/other.md"),
    )

    assert labels(suggestions) == ("docs/my file.md",)
    assert suggestions[0].insert_text == "@docs/my\\ file.md"


def test_completion_caps_results() -> None:
    suggestions = complete(
        "@src",
        file_candidates=tuple(f"src/file_{index}.py" for index in range(10)),
        limit=3,
    )

    assert labels(suggestions) == ("src/file_0.py", "src/file_1.py", "src/file_2.py")


def test_file_completion_filters_sensitive_generated_and_dependency_paths() -> None:
    suggestions = complete(
        "@",
        file_candidates=(
            ".env",
            "build/report.txt",
            "node_modules/package/index.js",
            "src/specode/completion.py",
            "secrets/api-token.txt",
            "tasks/task.md",
        ),
    )

    assert labels(suggestions) == ("src/specode/completion.py", "tasks/task.md")
