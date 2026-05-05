from __future__ import annotations

import json
import re
from pathlib import Path

from specode.artifacts import ArtifactStore, hash_text
from specode.cli import CommandRouter, RouteKind


def read_provenance(task_md: Path) -> dict[str, str | None]:
    match = re.match(
        r"\A<!-- specode-source\n(?P<json>.*?)\n-->",
        task_md.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group("json"))


def test_spec_text_creates_task_artifacts_with_text_provenance(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)

    result = router.route("/spec add password reset email flow")

    paths = ArtifactStore(tmp_path).task_paths("add-password-reset-email-flow")
    provenance = read_provenance(paths.task)
    assert result.kind == RouteKind.COMMAND
    assert paths.state.exists() and paths.task.exists() and paths.runs.is_dir()
    assert provenance["kind"] == "text"
    assert provenance["source_sha256"] == hash_text("add password reset email flow")


def test_spec_text_resumes_without_reimporting_task_provenance(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)
    router.route("/spec add password reset email flow")
    task_path = ArtifactStore(tmp_path).task_paths("add-password-reset-email-flow").task
    imported_at = read_provenance(task_path)["imported_at"]

    result = router.route("/spec add password reset email flow")

    assert "Resumed /spec task 'add-password-reset-email-flow'" in result.text
    assert read_provenance(task_path)["imported_at"] == imported_at


def test_spec_file_creates_task_artifacts_with_file_provenance(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "auth-reset" / "request.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Add password reset email flow\n\nSend reset links.\n", encoding="utf-8")
    router = CommandRouter(tmp_path)

    result = router.route("/spec incoming/auth-reset/request.md")

    paths = ArtifactStore(tmp_path).task_paths("auth-reset")
    provenance = read_provenance(paths.task)
    assert "Created /spec task 'auth-reset'" in result.text
    assert paths.state.exists() and paths.task.exists()
    assert provenance["source_path"] == "incoming/auth-reset/request.md"
    assert provenance["source_sha256"] == hash_text(source.read_text(encoding="utf-8"))


def test_spec_accepts_completed_file_reference_token(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "auth-reset" / "request.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Add password reset email flow\n\nSend reset links.\n", encoding="utf-8")
    router = CommandRouter(tmp_path)

    result = router.route("/spec @incoming/auth-reset/request.md")

    paths = ArtifactStore(tmp_path).task_paths("auth-reset")
    provenance = read_provenance(paths.task)
    assert "Created /spec task 'auth-reset'" in result.text
    assert provenance["source_path"] == "incoming/auth-reset/request.md"


def test_spec_file_resumes_without_reimporting_task_provenance(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "auth-reset" / "request.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Add password reset email flow\n\nSend reset links.\n", encoding="utf-8")
    router = CommandRouter(tmp_path)
    router.route("/spec incoming/auth-reset/request.md")
    task_path = ArtifactStore(tmp_path).task_paths("auth-reset").task
    imported_at = read_provenance(task_path)["imported_at"]

    result = router.route("/spec incoming/auth-reset/request.md")

    assert "Resumed /spec task 'auth-reset'" in result.text
    assert read_provenance(task_path)["imported_at"] == imported_at


def test_spec_file_resume_blocks_when_source_file_drifted(tmp_path: Path) -> None:
    source = tmp_path / "incoming" / "auth-reset" / "request.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Add password reset email flow\n", encoding="utf-8")
    router = CommandRouter(tmp_path)
    router.route("/spec incoming/auth-reset/request.md")
    source.write_text("# Add password reset email flow\n\nAlso expire tokens.\n", encoding="utf-8")

    result = router.route("/spec incoming/auth-reset/request.md")

    state = ArtifactStore(tmp_path).load_task_state("auth-reset")
    assert "Source drift detected" in result.text
    assert state.status == "blocked"
    assert state.artifacts.task == "stale"


def test_ordinary_input_still_does_not_create_spec_artifacts(tmp_path: Path) -> None:
    router = CommandRouter(tmp_path)

    result = router.route("help me understand this code")

    assert result.kind == RouteKind.CHAT
    assert not (tmp_path / "tasks").exists()
