from importlib.metadata import entry_points, version

import specode


def test_package_imports() -> None:
    assert specode.__version__ == version("specode")


def test_console_script_target_is_configured() -> None:
    scripts = entry_points(group="console_scripts")
    specode_script = next(script for script in scripts if script.name == "specode")

    assert specode_script.value == "specode:main"
