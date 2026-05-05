from __future__ import annotations

from rich.console import Console
from rich.text import Text

from specode.interactive import PromptConfig
from specode.ui import TerminalUI


INTRO_PROMISE = "Spec-driven coding in a quiet terminal loop."
INTRO_REQUIRED_TEXT = (
    "SpeCode",
    "Terminal Silver",
    INTRO_PROMISE,
    "|____/|",
    "/spec",
    "/steering",
    "/exit",
    "type /",
)
UNSUPPORTED_STARTUP_COMMANDS = (
    "/status",
    "/permissions",
    "/theme",
    "/help",
)


def render_intro_text(width: int = 88) -> str:
    console = Console(
        color_system=None,
        force_terminal=False,
        record=True,
        width=width,
    )
    TerminalUI(console).intro()

    return console.export_text(styles=False)


def assert_terminal_silver_intro_contract(output: str) -> None:
    assert all(text in output for text in INTRO_REQUIRED_TEXT)
    assert not any(command in output for command in UNSUPPORTED_STARTUP_COMMANDS)


def test_intro_renders_terminal_silver_start_screen() -> None:
    output = render_intro_text()

    assert_terminal_silver_intro_contract(output)
    assert any(label in output.lower() for label in ("mode", "type", "workspace"))
    assert output.count("\n") > 3


def test_intro_keeps_required_text_readable_at_narrow_width() -> None:
    output = render_intro_text(width=72)

    assert_terminal_silver_intro_contract(output)


def test_prompt_config_keeps_existing_prompt_text() -> None:
    assert PromptConfig().prompt_text == "specode> "


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
