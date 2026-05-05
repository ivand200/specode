"""Prompt-toolkit-backed interactive shell adapter for SpeCode."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, ThreadedCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory


class CompletionEngine(Protocol):
    """Pure completion engine contract used by the prompt adapter."""

    def complete(self, text: str, cursor_position: int) -> Iterable[Any]:
        """Return completion suggestions for text at cursor_position."""


class CommandRouter(Protocol):
    """Router shape needed by the interactive shell."""

    def route(self, raw_input: str) -> Any:
        """Route a submitted line and return a renderable result."""


RenderResult = Callable[[Any], None]


@dataclass(frozen=True)
class PromptConfig:
    """Prompt display options for the SpeCode shell."""

    prompt_text: str = "specode> "
    complete_while_typing: bool = True


class PromptToolkitCompleter(Completer):
    """Bridge pure SpeCode completion suggestions to prompt_toolkit."""

    def __init__(self, completion_engine: CompletionEngine | Callable[..., Iterable[Any]]):
        self._completion_engine = completion_engine

    def get_completions(
        self,
        document: Document,
        complete_event: Any,
    ) -> Iterable[Completion]:
        del complete_event
        suggestions = _call_completion_engine(
            self._completion_engine,
            document.text,
            document.cursor_position,
        )
        for suggestion in suggestions:
            yield suggestion_to_completion(suggestion, document.cursor_position)


class InteractiveShell:
    """Read submitted prompt lines and route them through injected collaborators."""

    def __init__(
        self,
        router: CommandRouter,
        render_result: RenderResult,
        *,
        session: PromptSession[str] | None = None,
        completion_engine: CompletionEngine | Callable[..., Iterable[Any]] | None = None,
        prompt_config: PromptConfig | None = None,
    ) -> None:
        self._router = router
        self._render_result = render_result
        self._prompt_config = prompt_config or PromptConfig()
        self._session = session or create_prompt_session(
            completion_engine,
            self._prompt_config,
        )

    def read_and_route_once(self) -> Any:
        """Read one submitted line, route it, render the result, and return it."""

        line = self._session.prompt(self._prompt_config.prompt_text)
        result = self._router.route(line)
        self._render_result(result)
        return result

    def run(self) -> None:
        """Run until EOF, Ctrl-C, or an exit route result."""

        while True:
            try:
                result = self.read_and_route_once()
            except (EOFError, KeyboardInterrupt):
                return

            if is_exit_result(result):
                return


def create_prompt_session(
    completion_engine: CompletionEngine | Callable[..., Iterable[Any]] | None,
    prompt_config: PromptConfig | None = None,
) -> PromptSession[str]:
    """Create a PromptSession with history, editing, and optional completions."""

    config = prompt_config or PromptConfig()
    completer: Completer | None = None
    if completion_engine is not None:
        completer = ThreadedCompleter(PromptToolkitCompleter(completion_engine))

    return PromptSession(
        completer=completer,
        complete_while_typing=config.complete_while_typing,
        history=InMemoryHistory(),
    )


def run_interactive_shell(
    router: CommandRouter,
    render_result: RenderResult,
    *,
    completion_engine: CompletionEngine | Callable[..., Iterable[Any]] | None = None,
    session: PromptSession[str] | None = None,
    prompt_config: PromptConfig | None = None,
) -> None:
    """Convenience function for future CLI wiring."""

    InteractiveShell(
        router,
        render_result,
        session=session,
        completion_engine=completion_engine,
        prompt_config=prompt_config,
    ).run()


def suggestion_to_completion(
    suggestion: Any,
    cursor_position: int,
) -> Completion:
    """Convert one pure suggestion object or mapping into a prompt_toolkit completion."""

    label = str(_suggestion_value(suggestion, "label", ""))
    insert_text = str(
        _suggestion_value(
            suggestion,
            "insert_text",
            label,
        )
    )
    description = _suggestion_value(suggestion, "description", "")
    kind = _suggestion_value(suggestion, "kind", "")
    replacement_start = int(
        _suggestion_value(suggestion, "replacement_start", cursor_position)
    )

    start_position = min(0, replacement_start - cursor_position)
    display = label or insert_text
    display_meta = _display_meta(kind, description)
    return Completion(
        insert_text,
        start_position=start_position,
        display=display,
        display_meta=display_meta,
    )


def is_exit_result(result: Any) -> bool:
    """Return True when a route result represents shell exit."""

    kind = getattr(result, "kind", None)
    value = getattr(kind, "value", kind)
    return value == "exit"


def _call_completion_engine(
    completion_engine: CompletionEngine | Callable[..., Iterable[Any]],
    text: str,
    cursor_position: int,
) -> Iterable[Any]:
    if callable(completion_engine):
        return completion_engine(text, cursor_position)

    complete = getattr(completion_engine, "complete", None)
    if complete is not None:
        return complete(text, cursor_position)

    suggest = getattr(completion_engine, "suggest", None)
    if suggest is not None:
        return suggest(text, cursor_position)

    suggestions = getattr(completion_engine, "suggestions", None)
    if suggestions is not None:
        return suggestions(text, cursor_position)

    raise TypeError("completion_engine must be callable or expose complete/suggest")


def _suggestion_value(suggestion: Any, name: str, default: Any) -> Any:
    if isinstance(suggestion, dict):
        return suggestion.get(name, default)
    return getattr(suggestion, name, default)


def _display_meta(kind: Any, description: Any) -> str:
    parts = [str(part) for part in (kind, description) if part]
    return " - ".join(parts)
