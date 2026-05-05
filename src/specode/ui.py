"""Restrained terminal output helpers for SpeCode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


_STYLE_BRAND = "bold bright_white"
_STYLE_LOGO_ACCENT = "bold #ff8f70"
_STYLE_ACCENT = "bold #ff8f70"
_STYLE_DIM = "grey58"
_STYLE_TEXT = "grey82"
_STYLE_LABEL = "bold grey70"
_STYLE_BORDER = "grey58"
_STYLE_PANEL = "#303031"
_INTRO_WORDMARK = (
    r"  ____             ____          _",
    r" / ___| _ __   ___ / ___|___   __| | ___",
    " \\___ \\| '_ \\ / _ \\ |   / _ \\ / _` |/ _ \\",
    r"  ___) | |_) |  __/ |__| (_) | (_| |  __/",
    r" |____/| .__/ \___|\____\___/ \__,_|\___|",
    r"       |_|",
)


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
                    self._intro_header(),
                    Text(
                        "Spec-driven coding in a quiet terminal loop.",
                        style=_STYLE_TEXT,
                    ),
                    self._intro_status_strip(),
                    self._intro_action_row(),
                    Text("Type / to discover commands.", style=_STYLE_DIM),
                ),
                border_style=_STYLE_BORDER,
                padding=(1, 2),
                style=_STYLE_PANEL,
                title=Text("SpeCode", style=_STYLE_LABEL),
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

    def _intro_header(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=2)
        table.add_column(ratio=1, justify="right")
        table.add_row(
            self._intro_wordmark(),
            Text("Terminal Silver", style=_STYLE_LABEL),
        )
        return table

    def _intro_wordmark(self) -> Text:
        wordmark = Text()
        accent_start = 20
        for index, line in enumerate(_INTRO_WORDMARK):
            if index:
                wordmark.append("\n")
            wordmark.append(line[:accent_start], style=_STYLE_BRAND)
            wordmark.append(line[accent_start:], style=_STYLE_LOGO_ACCENT)
        return wordmark

    def _intro_status_strip(self) -> Table:
        table = Table.grid(expand=True)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_column(ratio=1)
        table.add_row(
            self._status_chip("mode", "chat + /spec"),
            self._status_chip("type /", "commands"),
            self._status_chip("type @", "path hints"),
        )
        return table

    def _intro_action_row(self) -> Table:
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

    def _status_chip(self, label: str, value: str) -> Text:
        text = Text(label, style=_STYLE_LABEL)
        text.append(f" {value}", style=_STYLE_DIM)
        return text

    def _affordance(self, command: str, label: str) -> Text:
        text = Text(command, style=_STYLE_ACCENT)
        text.append(f" {label}", style=_STYLE_DIM)
        return text
