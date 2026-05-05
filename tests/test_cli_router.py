from pathlib import Path

import pytest
from typer.testing import CliRunner

from specode.cli import CommandRouter, RouteKind, app
from specode.runtime import ChatRequest, ChatResult, ChatRuntime


class RecordingChatRuntime(ChatRuntime):
    def __init__(self, response: str = "mocked chat output") -> None:
        self.response = response
        self.requests: list[ChatRequest] = []

    def run_chat(self, request: ChatRequest) -> ChatResult:
        self.requests.append(request)
        return ChatResult(text=self.response)


def assert_no_sdd_artifacts(workspace: Path) -> None:
    assert not (workspace / "tasks").exists()
    assert not (workspace / "steering").exists()


def test_ordinary_text_stays_normal_chat_without_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    chat_runtime = RecordingChatRuntime("chat says hello")
    router = CommandRouter(chat_runtime=chat_runtime)

    result = router.route("help me understand this code")

    assert result.kind == RouteKind.CHAT
    assert result.text == "chat says hello"
    assert chat_runtime.requests == [ChatRequest(message="help me understand this code")]
    assert_no_sdd_artifacts(tmp_path)


@pytest.mark.parametrize("line", ["@developer inspect this", "!pytest"])
def test_reserved_prefixes_do_not_route_to_chat_or_create_artifacts(
    line: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    chat_runtime = RecordingChatRuntime()
    router = CommandRouter(chat_runtime=chat_runtime)

    result = router.route(line)

    assert result.kind == RouteKind.RESERVED
    assert "reserved" in result.text
    assert chat_runtime.requests == []
    assert_no_sdd_artifacts(tmp_path)


def test_permissions_routes_to_placeholder_without_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    router = CommandRouter()

    result = router.route("/permissions")

    assert result.command == "permissions"
    assert "Permissions placeholder" in result.text
    assert_no_sdd_artifacts(tmp_path)


@pytest.mark.parametrize(
    ("line", "command"),
    [
        ("/spec add password reset", "spec"),
        ("/steering", "steering"),
        ("/status", "status"),
        ("/approve", "approve"),
        ("/revise clarify acceptance criteria", "revise"),
        ("/cancel", "cancel"),
    ],
)
def test_placeholder_slash_commands_are_recognized_without_creating_artifacts(
    line: str, command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    router = CommandRouter()

    result = router.route(line)

    assert result.command == command
    assert_no_sdd_artifacts(tmp_path)


def test_unknown_slash_command_is_reported_without_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    router = CommandRouter()

    result = router.route("/dance")

    assert result.kind == RouteKind.UNKNOWN
    assert_no_sdd_artifacts(tmp_path)


def test_interactive_shell_routes_lines_until_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    chat_runtime = RecordingChatRuntime("mocked chat output")
    monkeypatch.setattr(
        "specode.cli._default_chat_runtime",
        lambda: chat_runtime,
    )

    result = runner.invoke(app, input="hello\n/permissions\n/exit\n")

    assert result.exit_code == 0
    assert "mocked chat output" in result.output
    assert "Permissions placeholder" in result.output
    assert chat_runtime.requests == [ChatRequest(message="hello")]


def test_interactive_shell_reports_missing_openai_config_at_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    result = runner.invoke(app, input="/exit\n")

    assert result.exit_code == 0
    assert "OpenAI runtime blocked: OPENAI_API_KEY is not configured." in result.output
    assert result.output.index("OPENAI_API_KEY") < result.output.index("Session ended.")


def test_cli_loads_dotenv_before_building_default_chat_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    tmp_path.joinpath(".env").write_text("OPENAI_API_KEY=sk-dotenv\n", encoding="utf-8")

    router = CommandRouter(tmp_path)

    assert getattr(router.chat_runtime, "config").api_key == "sk-dotenv"
