"""Restrained terminal output helpers for SpeCode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class Printer(Protocol):
    """Small print protocol so tests can capture rendered messages."""

    def print(self, *objects: object, **kwargs: object) -> None:
        """Print objects to the terminal."""


@dataclass(frozen=True)
class UIMessage:
    """A rendered message with a semantic style."""

    text: str
    style: str = ""


class TerminalUI:
    """Small Rich facade for deterministic CLI messages."""

    def __init__(self, console: Printer | None = None) -> None:
        self._console = console or Console()

    def intro(self) -> None:
        self._console.print(
            Panel(
                Group(
                    Text("SpeCode", style="bold bright_white"),
                    Text("Spec-driven coding in a quiet terminal loop.", style="grey70"),
                    self._intro_affordances(),
                ),
                border_style="grey58",
                padding=(1, 2),
                subtitle=Text("Terminal Silver", style="grey62"),
            )
        )

    def assistant(self, text: str) -> None:
        self._emit(UIMessage(text, ""))

    def notice(self, text: str) -> None:
        self._emit(UIMessage(text, "cyan"))

    def warning(self, text: str) -> None:
        self._emit(UIMessage(text, "yellow"))

    def error(self, text: str) -> None:
        self._emit(UIMessage(text, "red"))

    def _emit(self, message: UIMessage) -> None:
        if message.style:
            self._console.print(Text(message.text, style=message.style))
            return

        self._console.print(message.text)

    def _intro_affordances(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_row(
            self._affordance("/spec", "task"),
            self._affordance("/steering", "docs"),
            self._affordance("/exit", "leave"),
        )
        return table

    def _affordance(self, command: str, label: str) -> Text:
        text = Text(command, style="bold #ff8f70")
        text.append(f" {label}", style="grey58")
        return text
