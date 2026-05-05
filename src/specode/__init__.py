"""SpeCode package bootstrap."""

__version__ = "0.1.0"


def main() -> None:
    """Run the SpeCode Typer application."""
    from specode.cli import main as cli_main

    cli_main()
