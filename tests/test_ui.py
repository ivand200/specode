from __future__ import annotations

from rich.console import Console
from rich.text import Text

from specode.ui import TerminalUI


def render_intro_text() -> str:
    console = Console(
        color_system=None,
        force_terminal=False,
        record=True,
        width=88,
    )
    TerminalUI(console).intro()

    return console.export_text(styles=False)


def test_intro_renders_terminal_silver_start_screen() -> None:
    output = render_intro_text()

    assert "SpeCode" in output
    assert "Terminal Silver" in output
    assert all(
        command in output
        for command in ["/spec", "/steering", "/exit"]
    )
    assert "/status" not in output
    assert "/permissions" not in output
    assert output.count("\n") > 3


class RecordingPrinter:
    def __init__(self) -> None:
        self.objects: list[object] = []

    def print(self, *objects: object, **kwargs: object) -> None:
        self.objects.extend(objects)


def test_message_methods_keep_existing_text_and_semantic_styles() -> None:
    printer = RecordingPrinter()
    ui = TerminalUI(printer)

    ui.assistant("plain response")
    ui.notice("noted")
    ui.warning("careful")
    ui.error("broken")

    assert printer.objects[0] == "plain response"
    styled_messages = printer.objects[1:]
    assert all(isinstance(message, Text) for message in styled_messages)
    assert [(message.plain, message.style) for message in styled_messages] == [
        ("noted", "cyan"),
        ("careful", "yellow"),
        ("broken", "red"),
    ]
