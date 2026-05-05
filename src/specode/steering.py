"""Project evidence collection for steering document generation."""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_SKIPPED_TOP_LEVEL = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "tasks",
    "vendor",
}
_PACKAGE_MANIFESTS = (
    "pyproject.toml",
    "package.json",
    "Cargo.toml",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
)


@dataclass(frozen=True)
class ProjectSurvey:
    """Compact repository facts used to seed durable steering docs."""

    root_name: str
    readme_name: str | None
    readme_summary: str | None
    package_name: str | None
    description: str | None
    package_manager: str | None
    stack: tuple[str, ...]
    dependencies: tuple[str, ...]
    dev_dependencies: tuple[str, ...]
    entry_points: tuple[str, ...]
    test_commands: tuple[str, ...]
    top_level_dirs: tuple[str, ...]
    source_dirs: tuple[str, ...]
    test_dirs: tuple[str, ...]
    config_files: tuple[str, ...]


def build_steering_docs(workspace_root: Path | str) -> dict[str, str]:
    """Return project-informed content for the three foundational steering docs."""

    survey = survey_project(Path(workspace_root))
    return {
        "product.md": _build_product_doc(survey),
        "tech.md": _build_tech_doc(survey),
        "structure.md": _build_structure_doc(survey),
    }


def survey_project(workspace_root: Path) -> ProjectSurvey:
    root = workspace_root.resolve()
    readme = _find_readme(root)
    readme_summary = _readme_summary(readme) if readme is not None else None
    pyproject = _load_toml(root / "pyproject.toml")
    package_json = _load_json(root / "package.json")

    package_name = _project_name(pyproject, package_json)
    description = _description(pyproject, package_json, readme_summary)
    dependencies = _dependencies(pyproject, package_json)
    dev_dependencies = _dev_dependencies(pyproject, package_json)
    entry_points = _entry_points(pyproject, package_json)
    top_level_dirs = _top_level_dirs(root)
    source_dirs = _source_dirs(root, top_level_dirs)
    test_dirs = tuple(name for name in ("tests", "test", "__tests__") if (root / name).is_dir())
    config_files = _config_files(root)
    stack = _stack(root, pyproject, package_json, top_level_dirs)
    package_manager = _package_manager(root)
    test_commands = _test_commands(root, pyproject, package_json, test_dirs)

    return ProjectSurvey(
        root_name=root.name,
        readme_name=readme.name if readme is not None else None,
        readme_summary=readme_summary,
        package_name=package_name,
        description=description,
        package_manager=package_manager,
        stack=stack,
        dependencies=dependencies,
        dev_dependencies=dev_dependencies,
        entry_points=entry_points,
        test_commands=test_commands,
        top_level_dirs=top_level_dirs,
        source_dirs=source_dirs,
        test_dirs=test_dirs,
        config_files=config_files,
    )


def _build_product_doc(survey: ProjectSurvey) -> str:
    product_name = survey.package_name or survey.root_name
    purpose = survey.description or f"{product_name} is the project in this repository."
    summary = survey.readme_summary
    readme_note = (
        f"- Primary product evidence comes from `{survey.readme_name}`."
        if survey.readme_name
        else "- No README was found; revise this document after product intent is clarified."
    )
    summary_note = f"- README summary: {summary}" if summary else readme_note

    return (
        "# Product\n\n"
        "## Purpose\n\n"
        f"- {purpose}\n"
        f"{summary_note}\n\n"
        "## Users / Actors\n\n"
        "- Primary users are the people running, maintaining, or integrating this project.\n"
        "- Contributors should treat these steering docs as durable project memory.\n\n"
        "## Core Workflows\n\n"
        "- Install or sync dependencies using the repository's documented package manager.\n"
        "- Run the project through its configured entry points or scripts.\n"
        "- Validate changes with the repository's test commands before handoff.\n\n"
        "## Core Domain Concepts\n\n"
        f"- Project/package name: `{product_name}`.\n"
        "- Durable product concepts should be added here when they are stable across tasks.\n\n"
        "## Scope Boundaries\n\n"
        "- Keep task-specific requirements, rollout notes, and temporary plans out of steering.\n"
        "- Prefer concise durable facts over generated inventories.\n\n"
        "## Durable Constraints\n\n"
        "- Do not persist secrets, credentials, or raw private environment data in steering docs.\n"
        "- Keep Markdown links relative so the docs remain portable after cloning.\n"
    )


def _build_tech_doc(survey: ProjectSurvey) -> str:
    stack_lines = _bullet_lines(survey.stack, fallback="Stack not detected from common manifests.")
    dependency_lines = _bullet_lines(
        _limit_items(survey.dependencies, 8),
        fallback="Runtime dependencies were not detected from common manifests.",
    )
    dev_dependency_lines = _bullet_lines(
        _limit_items(survey.dev_dependencies, 8),
        fallback="Development dependencies were not detected from common manifests.",
    )
    command_lines = _bullet_lines(
        survey.test_commands,
        fallback="Add the canonical test command here once it is known.",
    )
    package_manager = survey.package_manager or "No package manager lockfile detected."
    related = (
        "- Product and workflow guidance: [Product Steering](./product.md)\n"
        "- Repository boundaries and placement: [Structure Steering](./structure.md)"
    )

    return (
        "# Tech\n\n"
        "## Stack\n\n"
        f"{stack_lines}\n\n"
        "## Key Services / Infrastructure\n\n"
        f"- Package manager / runner signal: `{package_manager}`.\n"
        f"{dependency_lines}\n\n"
        "## Engineering Conventions\n\n"
        f"{dev_dependency_lines}\n"
        f"{command_lines}\n\n"
        "## Related Steering Docs\n\n"
        f"{related}\n\n"
        "## Technical Constraints\n\n"
        "- Prefer the repository's existing manifests, scripts, and test commands over ad hoc tooling.\n"
        "- Keep generated documentation compact and evidence-backed.\n"
    )


def _build_structure_doc(survey: ProjectSurvey) -> str:
    dirs = _bullet_lines(survey.top_level_dirs, fallback="No top-level directories detected.")
    source_dirs = _bullet_lines(survey.source_dirs, fallback="Source directory not detected.")
    test_dirs = _bullet_lines(survey.test_dirs, fallback="Test directory not detected.")
    entry_points = _bullet_lines(survey.entry_points, fallback="Entry points not detected.")
    config_files = _bullet_lines(survey.config_files, fallback="No common config files detected.")

    return (
        "# Structure\n\n"
        "## Repository Shape\n\n"
        f"{dirs}\n\n"
        "## Entry Points\n\n"
        f"{entry_points}\n\n"
        "## Architectural Conventions\n\n"
        f"- Source directories:\n{_indent(source_dirs)}\n"
        f"- Test directories:\n{_indent(test_dirs)}\n"
        f"- Configuration files:\n{_indent(config_files)}\n\n"
        "## Module Contract\n\n"
        "- Public behavior changes should be protected by focused tests at the nearest stable boundary.\n"
        "- Preserve existing module boundaries until repository evidence supports a refactor.\n\n"
        "## Module Interface Map\n\n"
        "| Boundary | Public Interface | Hidden Details | Protected By | Deeper Review When |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| Application code | Repository source modules and configured entry points | Private helpers, file layout details, and implementation sequence | Unit or behavior tests near the changed boundary | Changing public commands, APIs, data contracts, or cross-module responsibilities |\n"
        "| Validation | Repository test suite and configured test commands | Exact fixture internals and helper call order | Focused tests plus full suite before handoff | Changing workflow boundaries, persistence, permissions, or user-visible behavior |\n\n"
        "## Where To Put New Work\n\n"
        "- Put product code under the established source directory when one is present.\n"
        "- Put automated tests under the established test directory when one is present.\n"
        "- Update steering only for durable project facts that future tasks should not rediscover.\n"
    )


def _find_readme(root: Path) -> Path | None:
    for candidate in sorted(root.glob("README*")):
        if candidate.is_file():
            return candidate
    return None


def _readme_summary(readme: Path) -> str | None:
    try:
        text = readme.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for paragraph in re.split(r"\n\s*\n", text):
        stripped = paragraph.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stripped = re.sub(r"\s+", " ", stripped)
        return stripped[:300]
    return None


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError, UnicodeDecodeError):
        return {}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _project_name(pyproject: dict[str, Any], package_json: dict[str, Any]) -> str | None:
    return _string_at(pyproject, ("project", "name")) or _string(package_json.get("name"))


def _description(
    pyproject: dict[str, Any],
    package_json: dict[str, Any],
    readme_summary: str | None,
) -> str | None:
    return (
        _string_at(pyproject, ("project", "description"))
        or _string(package_json.get("description"))
        or readme_summary
    )


def _dependencies(
    pyproject: dict[str, Any],
    package_json: dict[str, Any],
) -> tuple[str, ...]:
    values: list[str] = []
    project_dependencies = pyproject.get("project", {}).get("dependencies", [])
    if isinstance(project_dependencies, list):
        values.extend(str(item) for item in project_dependencies)
    package_dependencies = package_json.get("dependencies", {})
    if isinstance(package_dependencies, dict):
        values.extend(package_dependencies.keys())
    return tuple(sorted(set(values), key=str.lower))


def _dev_dependencies(
    pyproject: dict[str, Any],
    package_json: dict[str, Any],
) -> tuple[str, ...]:
    values: list[str] = []
    dependency_groups = pyproject.get("dependency-groups", {})
    if isinstance(dependency_groups, dict):
        for group, deps in dependency_groups.items():
            if isinstance(deps, list):
                values.extend(f"{group}: {dep}" for dep in deps)
    package_dev = package_json.get("devDependencies", {})
    if isinstance(package_dev, dict):
        values.extend(package_dev.keys())
    return tuple(sorted(set(values), key=str.lower))


def _entry_points(
    pyproject: dict[str, Any],
    package_json: dict[str, Any],
) -> tuple[str, ...]:
    values: list[str] = []
    scripts = pyproject.get("project", {}).get("scripts", {})
    if isinstance(scripts, dict):
        values.extend(f"`{name}` -> `{target}`" for name, target in scripts.items())
    package_bin = package_json.get("bin", {})
    if isinstance(package_bin, dict):
        values.extend(f"`{name}` -> `{target}`" for name, target in package_bin.items())
    elif isinstance(package_bin, str):
        values.append(f"`{package_json.get('name', 'package')}` -> `{package_bin}`")
    package_scripts = package_json.get("scripts", {})
    if isinstance(package_scripts, dict):
        for name in ("dev", "start", "build", "test"):
            if name in package_scripts:
                values.append(f"`npm run {name}` -> `{package_scripts[name]}`")
    return tuple(values)


def _top_level_dirs(root: Path) -> tuple[str, ...]:
    names = [
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name not in _SKIPPED_TOP_LEVEL
    ]
    return tuple(sorted(names, key=str.lower))


def _source_dirs(root: Path, top_level_dirs: tuple[str, ...]) -> tuple[str, ...]:
    candidates = []
    for name in ("src", "app", "lib", "packages", "cmd", "internal"):
        if (root / name).is_dir():
            candidates.append(f"{name}/")
    if "src" in top_level_dirs:
        for child in sorted((root / "src").iterdir(), key=lambda path: path.name.lower()):
            if child.is_dir() and child.name != "__pycache__":
                candidates.append(f"src/{child.name}/")
    return tuple(dict.fromkeys(candidates))


def _config_files(root: Path) -> tuple[str, ...]:
    candidates = [
        *list(_PACKAGE_MANIFESTS),
        "uv.lock",
        "requirements.txt",
        "pytest.ini",
        "ruff.toml",
        ".python-version",
        "tsconfig.json",
        "vite.config.ts",
        "next.config.js",
    ]
    return tuple(name for name in candidates if (root / name).is_file())


def _stack(
    root: Path,
    pyproject: dict[str, Any],
    package_json: dict[str, Any],
    top_level_dirs: tuple[str, ...],
) -> tuple[str, ...]:
    values: list[str] = []
    if pyproject:
        requires_python = _string_at(pyproject, ("project", "requires-python"))
        values.append(f"Python package{f' ({requires_python})' if requires_python else ''}")
    if package_json:
        values.append("Node.js / JavaScript package")
    if (root / "Cargo.toml").is_file():
        values.append("Rust package")
    if (root / "go.mod").is_file():
        values.append("Go module")
    if "tests" in top_level_dirs or "test" in top_level_dirs:
        values.append("Automated tests are present")
    return tuple(values)


def _package_manager(root: Path) -> str | None:
    if (root / "uv.lock").is_file():
        return "uv"
    if (root / "poetry.lock").is_file():
        return "Poetry"
    if (root / "package-lock.json").is_file():
        return "npm"
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "Yarn"
    if (root / "Cargo.lock").is_file():
        return "Cargo"
    if (root / "go.mod").is_file():
        return "Go tooling"
    return None


def _test_commands(
    root: Path,
    pyproject: dict[str, Any],
    package_json: dict[str, Any],
    test_dirs: tuple[str, ...],
) -> tuple[str, ...]:
    commands: list[str] = []
    package_scripts = package_json.get("scripts", {})
    if isinstance(package_scripts, dict) and "test" in package_scripts:
        commands.append("npm test")
    if pyproject and test_dirs:
        runner = "uv run " if (root / "uv.lock").is_file() else ""
        commands.append(f"{runner}pytest")
    return tuple(dict.fromkeys(commands))


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_at(data: dict[str, Any], path: tuple[str, ...]) -> str | None:
    current: Any = data
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _string(current)


def _bullet_lines(items: tuple[str, ...], *, fallback: str) -> str:
    if not items:
        return f"- {fallback}"
    return "\n".join(f"- {item}" for item in items)


def _limit_items(items: tuple[str, ...], limit: int) -> tuple[str, ...]:
    if len(items) <= limit:
        return items
    remaining = len(items) - limit
    return (*items[:limit], f"...and {remaining} more")


def _indent(text: str) -> str:
    return "\n".join(f"  {line}" for line in text.splitlines())
