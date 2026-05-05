"""Slash command metadata for SpeCode terminal helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Iterator


def _normalize_command_token(token: str) -> str:
    normalized = token.strip().lower()
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized


@dataclass(frozen=True)
class CommandDefinition:
    """Display and lookup metadata for one slash command."""

    name: str
    description: str
    usage: str
    category: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    hidden: bool = False
    accepts_args: bool = False

    def __post_init__(self) -> None:
        name = _normalize_command_token(self.name)
        aliases = tuple(_normalize_command_token(alias) for alias in self.aliases)

        if not name:
            raise ValueError("Command name must not be empty.")
        if any(not alias for alias in aliases):
            raise ValueError("Command aliases must not be empty.")
        if name in aliases:
            raise ValueError(f"Command '{name}' cannot alias itself.")
        if not self.description.strip():
            raise ValueError(f"Command '{name}' needs a description.")
        if not self.usage.strip().startswith("/"):
            raise ValueError(f"Command '{name}' usage must start with '/'.")
        if not self.category.strip():
            raise ValueError(f"Command '{name}' needs a category.")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "usage", self.usage.strip())
        object.__setattr__(self, "category", self.category.strip())

    @property
    def slash_name(self) -> str:
        """Return the canonical slash form used in completion labels."""

        return f"/{self.name}"

    @property
    def slash_aliases(self) -> tuple[str, ...]:
        """Return aliases in slash form."""

        return tuple(f"/{alias}" for alias in self.aliases)

    def matches(self, token: str) -> bool:
        """Return whether a name or alias refers to this command."""

        normalized = _normalize_command_token(token)
        return normalized == self.name or normalized in self.aliases


class CommandCatalog:
    """Ordered command definitions with name and alias lookup."""

    def __init__(self, commands: Iterable[CommandDefinition]) -> None:
        self._commands = tuple(commands)
        self._lookup: dict[str, CommandDefinition] = {}

        for command in self._commands:
            self._register(command.name, command)
            for alias in command.aliases:
                self._register(alias, command)

    def _register(self, token: str, command: CommandDefinition) -> None:
        if token in self._lookup:
            existing = self._lookup[token]
            raise ValueError(
                f"Command token '/{token}' is used by both "
                f"'/{existing.name}' and '/{command.name}'."
            )
        self._lookup[token] = command

    def lookup(self, token: str) -> CommandDefinition | None:
        """Look up a command by name or alias, with or without a leading slash."""

        return self._lookup.get(_normalize_command_token(token))

    def require(self, token: str) -> CommandDefinition:
        """Look up a command and raise KeyError when it is absent."""

        command = self.lookup(token)
        if command is None:
            raise KeyError(f"Unknown slash command: /{_normalize_command_token(token)}")
        return command

    def commands(self, *, include_hidden: bool = False) -> tuple[CommandDefinition, ...]:
        """Return commands in deterministic catalog order."""

        if include_hidden:
            return self._commands
        return self.visible_commands()

    def visible_commands(self) -> tuple[CommandDefinition, ...]:
        """Return non-hidden commands in deterministic catalog order."""

        return tuple(command for command in self._commands if not command.hidden)

    def __iter__(self) -> Iterator[CommandDefinition]:
        return iter(self._commands)

    def __len__(self) -> int:
        return len(self._commands)


def default_command_catalog() -> CommandCatalog:
    """Return SpeCode's built-in slash command catalog."""

    return CommandCatalog(
        (
            CommandDefinition(
                name="spec",
                description="Start or resume a spec-driven task.",
                usage="/spec <task description or path-to-task.md>",
                category="workflow",
                accepts_args=True,
            ),
            CommandDefinition(
                name="steering",
                description="Create missing/default project steering docs.",
                usage="/steering",
                category="workflow",
            ),
            CommandDefinition(
                name="exit",
                aliases=("quit",),
                description="End the interactive session.",
                usage="/exit",
                category="session",
            ),
        )
    )
