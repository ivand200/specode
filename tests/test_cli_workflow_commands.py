from __future__ import annotations

from pathlib import Path

import pytest

from specode.artifacts import ArtifactStore
from specode.cli import CommandRouter, RouteKind


def test_steering_creates_three_docs_without_task_artifacts(tmp_path: Path) -> None:
    tmp_path.joinpath("README.md").write_text(
        "# Example Tool\n\nExample Tool processes invoices from the command line.\n",
        encoding="utf-8",
    )
    tmp_path.joinpath("pyproject.toml").write_text(
        "\n".join(
            [
                "[project]",
                'name = "example-tool"',
                'description = "A CLI for invoice processing."',
                'requires-python = ">=3.11"',
                'dependencies = ["typer>=0.12"]',
                "",
                "[project.scripts]",
                'example = "example:main"',
                "",
                "[dependency-groups]",
                'dev = ["pytest>=8.0"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    tmp_path.joinpath("src", "example").mkdir(parents=True)
    tmp_path.joinpath("tests").mkdir()
    router = CommandRouter(tmp_path)

    result = router.route("/steering")

    assert result.kind == RouteKind.COMMAND
    assert "Created from repository scan: product.md, tech.md, structure.md." in result.text
    assert (tmp_path / "steering" / "product.md").exists()
    assert (tmp_path / "steering" / "tech.md").exists()
    assert (tmp_path / "steering" / "structure.md").exists()
    assert "A CLI for invoice processing." in (tmp_path / "steering" / "product.md").read_text(
        encoding="utf-8"
    )
    assert "typer>=0.12" in (tmp_path / "steering" / "tech.md").read_text(encoding="utf-8")
    assert "`example` -> `example:main`" in (
        tmp_path / "steering" / "structure.md"
    ).read_text(encoding="utf-8")
    assert not (tmp_path / "tasks").exists()


def test_steering_preserves_existing_docs(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_steering_text("product.md", "# Product\n\nAlready curated.\n")
    router = CommandRouter(tmp_path)

    result = router.route("/steering")

    assert "Preserved existing: product.md." in result.text
    assert store.read_steering_text("product.md") == "# Product\n\nAlready curated.\n"
    assert (tmp_path / "steering" / "tech.md").exists()
    assert (tmp_path / "steering" / "structure.md").exists()


def test_steering_refreshes_old_default_placeholders(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.ensure_steering_docs()
    tmp_path.joinpath("pyproject.toml").write_text(
        '[project]\nname = "researched-app"\ndescription = "Evidence-backed app."\n',
        encoding="utf-8",
    )
    router = CommandRouter(tmp_path)

    result = router.route("/steering")

    assert "Refreshed default placeholders: product.md, tech.md, structure.md." in result.text
    assert "Evidence-backed app." in store.read_steering_text("product.md")


def test_steering_omits_generated_and_artifact_directories_from_structure(
    tmp_path: Path,
) -> None:
    tmp_path.joinpath("pyproject.toml").write_text(
        '[project]\nname = "filtered-app"\n',
        encoding="utf-8",
    )
    for dirname in (
        ".cache",
        ".next",
        ".turbo",
        "coverage",
        "node_modules",
        "tasks",
        "vendor",
    ):
        tmp_path.joinpath(dirname).mkdir()
    tmp_path.joinpath("src", "filtered_app").mkdir(parents=True)
    tmp_path.joinpath("tests").mkdir()
    router = CommandRouter(tmp_path)

    router.route("/steering")

    structure = ArtifactStore(tmp_path).read_steering_text("structure.md")
    assert "src/" in structure
    assert "tests" in structure
    for dirname in ("coverage", "node_modules", "tasks", "vendor", ".next"):
        assert f"- {dirname}" not in structure


def test_spec_does_not_create_or_rewrite_steering(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    store.write_steering_text("tech.md", "# Tech\n\nKeep this.\n")
    router = CommandRouter(tmp_path)

    result = router.route("/spec add password reset email flow")

    assert "Created /spec task 'add-password-reset-email-flow'" in result.text
    assert store.read_steering_text("tech.md") == "# Tech\n\nKeep this.\n"
    assert not (tmp_path / "steering" / "product.md").exists()
    assert not (tmp_path / "steering" / "structure.md").exists()


@pytest.mark.parametrize(
    "line",
    [
        "/status",
        "/approve",
        "/revise clarify acceptance criteria",
        "/cancel duplicate request",
        "/run fake",
        "/permissions",
    ],
)
def test_removed_workflow_slash_commands_are_unknown(tmp_path: Path, line: str) -> None:
    router = CommandRouter(tmp_path)

    result = router.route(line)

    assert result.kind == RouteKind.UNKNOWN
    assert result.text.startswith("Unknown slash command:")
    assert not (tmp_path / "tasks").exists()
