"""Pure completion helpers for SpeCode interactive input."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Iterable, Protocol

try:  # pragma: no cover - exercised once the command catalog task lands.
    from specode.commands import CommandCatalog, default_command_catalog
except ImportError:  # pragma: no cover - current task can run before Task 2.
    CommandCatalog = Any  # type: ignore[misc,assignment]

    def default_command_catalog() -> None:
        return None


DEFAULT_SUGGESTION_LIMIT = 8


class CompletionMode(str, Enum):
    """Completion modes understood by the interactive prompt adapter."""

    IDLE = "idle"
    SLASH = "slash"
    FILE = "file"


class SuggestionKind(str, Enum):
    """Kinds of suggestions returned by the completion engine."""

    COMMAND = "command"
    FILE = "file"
    DIRECTORY = "directory"


@dataclass(frozen=True)
class CompletionContext:
    """The active completion token at a cursor position."""

    mode: CompletionMode
    token: str
    replacement_start: int
    replacement_end: int


@dataclass(frozen=True)
class Suggestion:
    """A single completion suggestion with enough data to replace text."""

    label: str
    insert_text: str
    description: str
    kind: SuggestionKind
    replacement_start: int
    replacement_end: int
    score: int


@dataclass(frozen=True)
class FileCandidate:
    """A workspace-relative file or directory candidate."""

    path: str
    is_directory: bool = False
    description: str = ""


class _CommandDefinition(Protocol):
    name: str
    description: str
    hidden: bool


def detect_completion_context(
    text: str,
    cursor_position: int | None = None,
) -> CompletionContext:
    """Detect the completion mode for the active token.

    Active ``@`` tokens win over slash context so prompts such as
    ``/spec @task`` still offer file-reference suggestions.
    """

    cursor = _clamp_cursor(text, cursor_position)
    token_start, token_end = _active_token_bounds(text, cursor)
    raw_token = text[token_start:token_end]
    token_to_cursor = text[token_start:cursor]

    if _is_file_reference_token(raw_token):
        at_offset = raw_token.index("@")
        replacement_start = token_start + at_offset
        token_fragment = text[replacement_start + 1 : cursor]
        return CompletionContext(
            mode=CompletionMode.FILE,
            token=_unescape_token(token_fragment),
            replacement_start=replacement_start,
            replacement_end=token_end,
        )

    if token_to_cursor.startswith("/") and _slash_token_is_active(text, token_start):
        return CompletionContext(
            mode=CompletionMode.SLASH,
            token=token_to_cursor[1:],
            replacement_start=token_start,
            replacement_end=token_end,
        )

    return CompletionContext(
        mode=CompletionMode.IDLE,
        token="",
        replacement_start=cursor,
        replacement_end=cursor,
    )


def complete(
    text: str,
    cursor_position: int | None = None,
    *,
    catalog: CommandCatalog | None = None,
    file_candidates: Iterable[str | FileCandidate] = (),
    limit: int = DEFAULT_SUGGESTION_LIMIT,
) -> tuple[Suggestion, ...]:
    """Return completion suggestions for the active token."""

    context = detect_completion_context(text, cursor_position)
    if context.mode == CompletionMode.SLASH:
        return complete_slash(context, catalog=catalog, limit=limit)
    if context.mode == CompletionMode.FILE:
        return complete_file(context, file_candidates, limit=limit)
    return ()


def complete_slash(
    context_or_prefix: CompletionContext | str,
    *,
    catalog: CommandCatalog | None = None,
    limit: int = DEFAULT_SUGGESTION_LIMIT,
) -> tuple[Suggestion, ...]:
    """Complete slash commands from a command catalog."""

    context = _context_from_prefix(context_or_prefix, CompletionMode.SLASH)
    prefix = context.token.lower()
    commands = _visible_commands(catalog)
    suggestions: list[Suggestion] = []

    for order, command in enumerate(commands):
        names = _command_names(command)
        if not names:
            continue
        primary_name = names[0]
        match_score = _command_match_score(prefix, names)
        if match_score is None:
            continue
        suggestions.append(
            Suggestion(
                label=f"/{primary_name}",
                insert_text=f"/{primary_name} ",
                description=_command_description(command),
                kind=SuggestionKind.COMMAND,
                replacement_start=context.replacement_start,
                replacement_end=context.replacement_end,
                score=match_score - order,
            )
        )

    return _cap_suggestions(suggestions, limit)


def complete_file(
    context_or_prefix: CompletionContext | str,
    candidates: Iterable[str | FileCandidate],
    *,
    limit: int = DEFAULT_SUGGESTION_LIMIT,
) -> tuple[Suggestion, ...]:
    """Complete workspace-relative file references from supplied candidates."""

    context = _context_from_prefix(context_or_prefix, CompletionMode.FILE)
    prefix = _normalize_candidate_path(context.token)
    suggestions: list[Suggestion] = []

    for order, raw_candidate in enumerate(candidates):
        candidate = _coerce_file_candidate(raw_candidate)
        path = _normalize_candidate_path(candidate.path)
        if not path or _is_denylisted_path(path):
            continue

        display_path = _display_candidate_path(path, candidate.is_directory)
        comparable_path = display_path.rstrip("/")
        score = _file_match_score(prefix, comparable_path)
        if score is None:
            continue

        kind = (
            SuggestionKind.DIRECTORY
            if candidate.is_directory or display_path.endswith("/")
            else SuggestionKind.FILE
        )
        suggestions.append(
            Suggestion(
                label=display_path,
                insert_text=f"@{_escape_token(display_path)}",
                description=candidate.description,
                kind=kind,
                replacement_start=context.replacement_start,
                replacement_end=context.replacement_end,
                score=score - order,
            )
        )

    return _cap_suggestions(suggestions, limit)


def _clamp_cursor(text: str, cursor_position: int | None) -> int:
    if cursor_position is None:
        return len(text)
    return max(0, min(cursor_position, len(text)))


def _active_token_bounds(text: str, cursor: int) -> tuple[int, int]:
    start = cursor
    while start > 0 and not _is_unescaped_whitespace(text, start - 1):
        start -= 1

    end = cursor
    while end < len(text) and not _is_unescaped_whitespace(text, end):
        end += 1

    return start, end


def _is_unescaped_whitespace(text: str, index: int) -> bool:
    return text[index].isspace() and not _is_escaped(text, index)


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    probe = index - 1
    while probe >= 0 and text[probe] == "\\":
        backslashes += 1
        probe -= 1
    return backslashes % 2 == 1


def _is_file_reference_token(token: str) -> bool:
    if "@" not in token:
        return False
    at_index = token.find("@")
    return at_index == 0 or token[at_index - 1].isspace()


def _slash_token_is_active(text: str, token_start: int) -> bool:
    return text[:token_start].strip() == ""


def _unescape_token(token: str) -> str:
    value: list[str] = []
    escaped = False
    for char in token:
        if escaped:
            value.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            value.append(char)
    if escaped:
        value.append("\\")
    return "".join(value)


def _escape_token(token: str) -> str:
    escaped: list[str] = []
    for char in token:
        if char.isspace() or char == "\\":
            escaped.append("\\")
        escaped.append(char)
    return "".join(escaped)


def _context_from_prefix(
    context_or_prefix: CompletionContext | str,
    mode: CompletionMode,
) -> CompletionContext:
    if isinstance(context_or_prefix, CompletionContext):
        return context_or_prefix
    return CompletionContext(
        mode=mode,
        token=context_or_prefix,
        replacement_start=0,
        replacement_end=len(context_or_prefix),
    )


def _visible_commands(catalog: CommandCatalog | None) -> tuple[Any, ...]:
    if catalog is None:
        catalog = default_command_catalog()
    if catalog is None:
        return ()

    for method_name in ("visible_commands", "visible", "commands"):
        member = getattr(catalog, method_name, None)
        if callable(member):
            return tuple(command for command in member() if not _command_hidden(command))
        if member is not None and not callable(member):
            values = member.values() if isinstance(member, dict) else member
            return tuple(command for command in values if not _command_hidden(command))

    if isinstance(catalog, Iterable):
        return tuple(command for command in catalog if not _command_hidden(command))
    return ()


def _command_hidden(command: Any) -> bool:
    return bool(getattr(command, "hidden", False))


def _command_names(command: Any) -> tuple[str, ...]:
    primary = str(getattr(command, "name", "")).lstrip("/")
    aliases = tuple(str(alias).lstrip("/") for alias in getattr(command, "aliases", ()))
    return tuple(name for name in (primary, *aliases) if name)


def _command_description(command: Any) -> str:
    return str(getattr(command, "description", ""))


def _command_match_score(prefix: str, names: tuple[str, ...]) -> int | None:
    lowered_names = tuple(name.lower() for name in names)
    if prefix == "":
        return 1000
    if prefix in lowered_names:
        return 950
    if any(name.startswith(prefix) for name in lowered_names):
        return 900
    return None


def _coerce_file_candidate(candidate: str | FileCandidate) -> FileCandidate:
    if isinstance(candidate, FileCandidate):
        return candidate
    path = str(candidate)
    return FileCandidate(path=path, is_directory=path.endswith("/"))


def _normalize_candidate_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    if normalized in {"", "."}:
        return ""
    return str(PurePosixPath(normalized))


def _display_candidate_path(path: str, is_directory: bool) -> str:
    display_path = path.rstrip("/")
    if is_directory:
        return f"{display_path}/"
    return display_path


def _file_match_score(prefix: str, path: str) -> int | None:
    lowered_prefix = prefix.lower()
    lowered_path = path.lower()
    basename = PurePosixPath(path).name.lower()

    if lowered_prefix == "":
        return 800
    if lowered_path == lowered_prefix:
        return 780
    if lowered_path.startswith(lowered_prefix):
        return 760
    if basename.startswith(lowered_prefix):
        return 700
    return None


_DENYLISTED_PARTS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".cache",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        ".next",
        ".svelte-kit",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "secrets",
        "target",
        "vendor",
        "venv",
    }
)

_SENSITIVE_FILENAMES = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".npmrc",
        ".pypirc",
        "credentials",
        "credentials.json",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "secrets",
    }
)

_SENSITIVE_SUFFIXES = (
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".crt",
    ".cer",
)

_SENSITIVE_SUBSTRINGS = (
    "secret",
    "password",
    "passwd",
    "credential",
    "private_key",
)


def _is_denylisted_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    lowered_parts = tuple(part.lower() for part in parts)
    if any(part in _DENYLISTED_PARTS for part in lowered_parts):
        return True

    filename = lowered_parts[-1] if lowered_parts else ""
    if filename in _SENSITIVE_FILENAMES:
        return True
    if filename.startswith(".env."):
        return True
    if filename.endswith(_SENSITIVE_SUFFIXES):
        return True
    return any(marker in filename for marker in _SENSITIVE_SUBSTRINGS)


def _cap_suggestions(
    suggestions: Iterable[Suggestion],
    limit: int,
) -> tuple[Suggestion, ...]:
    if limit <= 0:
        return ()
    ordered = sorted(
        suggestions,
        key=lambda suggestion: (
            -suggestion.score,
            suggestion.kind != SuggestionKind.DIRECTORY,
            suggestion.label.lower(),
        ),
    )
    return tuple(ordered[:limit])
