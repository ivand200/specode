import pytest

from specode.commands import (
    CommandCatalog,
    CommandDefinition,
    default_command_catalog,
)


def test_default_catalog_exposes_required_visible_commands_in_order() -> None:
    catalog = default_command_catalog()

    assert [command.slash_name for command in catalog.visible_commands()] == [
        "/spec",
        "/steering",
        "/exit",
    ]


def test_default_catalog_lookups_accept_names_slashes_and_aliases() -> None:
    catalog = default_command_catalog()

    assert catalog.lookup("spec").name == "spec"
    assert catalog.lookup("/spec").name == "spec"
    assert catalog.lookup("quit").name == "exit"
    assert catalog.lookup("/quit").name == "exit"
    assert catalog.lookup("/unknown") is None


def test_default_catalog_has_concise_display_metadata() -> None:
    catalog = default_command_catalog()

    for command in catalog.visible_commands():
        assert command.description
        assert len(command.description) <= 72
        assert command.usage.startswith("/")
        assert command.category in {"workflow", "session"}
        assert isinstance(command.accepts_args, bool)


def test_accepts_args_metadata_tracks_commands_that_take_arguments() -> None:
    catalog = default_command_catalog()

    assert catalog.require("/spec").accepts_args
    assert not catalog.require("/exit").accepts_args


def test_hidden_commands_are_available_but_excluded_from_visible_commands() -> None:
    catalog = CommandCatalog(
        (
            CommandDefinition(
                name="visible",
                description="Visible command.",
                usage="/visible",
                category="test",
            ),
            CommandDefinition(
                name="internal",
                description="Internal command.",
                usage="/internal",
                category="test",
                hidden=True,
            ),
        )
    )

    assert [command.name for command in catalog.visible_commands()] == ["visible"]
    assert [command.name for command in catalog.commands(include_hidden=True)] == [
        "visible",
        "internal",
    ]
    assert catalog.lookup("/internal").hidden


def test_command_definition_normalizes_case_and_slashes() -> None:
    command = CommandDefinition(
        name="/Visible",
        aliases=("/V",),
        description="Visible command.",
        usage="/visible",
        category="workflow",
    )

    assert command.name == "visible"
    assert command.aliases == ("v",)
    assert command.matches("/V")
    assert command.slash_aliases == ("/v",)


def test_catalog_rejects_duplicate_names_or_aliases() -> None:
    with pytest.raises(ValueError, match="/same"):
        CommandCatalog(
            (
                CommandDefinition(
                    name="same",
                    description="First command.",
                    usage="/same",
                    category="test",
                ),
                CommandDefinition(
                    name="other",
                    aliases=("same",),
                    description="Second command.",
                    usage="/other",
                    category="test",
                ),
            )
        )
