"""Repo-local artifact storage for SpeCode SDD task and steering files."""

from __future__ import annotations

import json
import os
import re
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PureWindowsPath
from typing import Any
from urllib.parse import urlparse, unquote


TASK_ARTIFACTS = frozenset(
    {
        "state.json",
        "task.md",
        "context.md",
        "design.md",
        "tasks.md",
    }
)
STEERING_DOC_ORDER = ("product.md", "tech.md", "structure.md")
STEERING_DOCS = frozenset(STEERING_DOC_ORDER)
DEFAULT_STEERING_DOCS = {
    "product.md": (
        "# Product\n\n"
        "## Durable Facts\n\n"
        "- Capture product goals, users, workflows, and non-goals here.\n"
    ),
    "tech.md": (
        "# Tech\n\n"
        "## Durable Facts\n\n"
        "- Capture stack, dependencies, commands, environments, and constraints here.\n"
    ),
    "structure.md": (
        "# Structure\n\n"
        "## Durable Facts\n\n"
        "- Capture module boundaries, public interfaces, and ownership rules here.\n"
    ),
}

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MARKDOWN_INLINE_LINK_RE = re.compile(r"!?\[[^\]]*]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_MARKDOWN_REFERENCE_LINK_RE = re.compile(r"^\s*\[[^\]]+]:\s+(\S+)", re.MULTILINE)
_MARKDOWN_AUTOLINK_RE = re.compile(r"<(file://[^>]+)>", re.IGNORECASE)
_SOURCE_PROVENANCE_RE = re.compile(
    r"\A<!-- specode-source\n(?P<json>.*?)\n-->\n?",
    re.DOTALL,
)


class ArtifactStoreError(ValueError):
    """Raised when an artifact path or content violates store policy."""


@dataclass(frozen=True)
class TaskArtifactPaths:
    """Common paths for one task artifact directory."""

    root: Path
    state: Path
    task: Path
    context: Path
    design: Path
    tasks: Path
    runs: Path


@dataclass(frozen=True)
class TaskSourceProvenance:
    """Source metadata persisted in imported ``task.md`` artifacts."""

    kind: str
    source_sha256: str
    imported_at: str
    source_path: str | None = None

    @classmethod
    def from_text(cls, text: str) -> "TaskSourceProvenance":
        return cls(
            kind="text",
            source_sha256=hash_text(text),
            imported_at=_utc_timestamp(),
        )

    @classmethod
    def from_file(
        cls,
        path: Path,
        text: str,
        workspace_root: Path,
    ) -> "TaskSourceProvenance":
        return cls(
            kind="file",
            source_path=_display_source_path(path, workspace_root),
            source_sha256=hash_text(text),
            imported_at=_utc_timestamp(),
        )

    def to_dict(self) -> dict[str, str | None]:
        return {
            "kind": self.kind,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "imported_at": self.imported_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskSourceProvenance":
        return cls(
            kind=str(data["kind"]),
            source_path=data.get("source_path"),
            source_sha256=str(data["source_sha256"]),
            imported_at=str(data["imported_at"]),
        )


class ArtifactStore:
    """Read and write SpeCode artifacts under a workspace root.

    ArtifactStore owns only SDD artifacts in ``tasks/`` and durable project
    guidance in ``steering/``. Product code mutation belongs to later tools.
    """

    def __init__(self, workspace_root: Path | str) -> None:
        self.workspace_root = Path(workspace_root).resolve()

    @property
    def tasks_root(self) -> Path:
        return self.workspace_root / "tasks"

    @property
    def steering_root(self) -> Path:
        return self.workspace_root / "steering"

    def task_dir(self, task_name: str) -> Path:
        return self._scoped_path(self.tasks_root / self._validate_name(task_name, "task name"))

    def task_paths(self, task_name: str) -> TaskArtifactPaths:
        task_root = self.task_dir(task_name)
        return TaskArtifactPaths(
            root=task_root,
            state=task_root / "state.json",
            task=task_root / "task.md",
            context=task_root / "context.md",
            design=task_root / "design.md",
            tasks=task_root / "tasks.md",
            runs=task_root / "runs",
        )

    def ensure_task_dir(self, task_name: str) -> Path:
        paths = self.task_paths(task_name)
        paths.runs.mkdir(parents=True, exist_ok=True)
        return paths.root

    def ensure_runs_dir(self, task_name: str) -> Path:
        runs_dir = self.task_paths(task_name).runs
        runs_dir.mkdir(parents=True, exist_ok=True)
        return runs_dir

    def task_artifact_path(self, task_name: str, artifact_name: str) -> Path:
        self._validate_member(artifact_name, TASK_ARTIFACTS, "task artifact")
        return self.task_dir(task_name) / artifact_name

    def source_file_path(self, source_path: Path | str) -> Path:
        """Resolve a source task file path inside the workspace."""

        path = Path(source_path).expanduser()
        if not path.is_absolute():
            path = self.workspace_root / path
        return self._scoped_path(path)

    def read_source_task_file(self, source_path: Path | str) -> tuple[Path, str]:
        """Read a Markdown task source file from inside the workspace."""

        resolved = self.source_file_path(source_path)
        if resolved.suffix.lower() != ".md":
            raise ArtifactStoreError(f"Source task file must be Markdown: {source_path}")
        if not resolved.is_file():
            raise ArtifactStoreError(f"Source task file does not exist: {source_path}")
        return resolved, resolved.read_text(encoding="utf-8")

    def run_path(self, task_name: str, run_id: str) -> Path:
        run_name = self._validate_name(run_id, "run id")
        if not run_name.endswith(".json"):
            run_name = f"{run_name}.json"
        return self.task_paths(task_name).runs / run_name

    def ensure_steering_dir(self) -> Path:
        self.steering_root.mkdir(parents=True, exist_ok=True)
        return self.steering_root

    def ensure_steering_docs(
        self,
        contents: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Create or refresh missing/default steering docs.

        Existing docs are preserved so /steering does not overwrite durable
        project context gathered by the user or another worker.
        """

        self.ensure_steering_dir()
        statuses: dict[str, str] = {}
        for doc_name in STEERING_DOC_ORDER:
            path = self.steering_doc_path(doc_name)
            desired_content = (
                contents.get(doc_name, DEFAULT_STEERING_DOCS[doc_name])
                if contents is not None
                else DEFAULT_STEERING_DOCS[doc_name]
            )
            if path.exists():
                existing_content = self.read_text(path)
                if _is_default_steering_doc(doc_name, existing_content) and (
                    desired_content.strip() != existing_content.strip()
                ):
                    self.write_text(path, desired_content)
                    statuses[doc_name] = "updated"
                else:
                    statuses[doc_name] = "preserved"
                continue
            self.write_text(path, desired_content)
            statuses[doc_name] = "created"
        return statuses

    def steering_doc_path(self, doc_name: str) -> Path:
        self._validate_member(doc_name, STEERING_DOCS, "steering doc")
        return self._scoped_path(self.steering_root / doc_name)

    def read_text(self, path: Path | str) -> str:
        return self._scoped_path(Path(path)).read_text(encoding="utf-8")

    def write_text(self, path: Path | str, content: str) -> Path:
        artifact_path = self._scoped_path(Path(path))
        if artifact_path.suffix == ".md":
            validate_link_safe_markdown(content)
        self._atomic_write_text(artifact_path, content)
        return artifact_path

    def read_json(self, path: Path | str) -> dict[str, Any]:
        return json.loads(self.read_text(path))

    def write_json(self, path: Path | str, data: dict[str, Any]) -> Path:
        artifact_path = self._scoped_path(Path(path))
        content = json.dumps(data, indent=2, sort_keys=True)
        self._atomic_write_text(artifact_path, f"{content}\n")
        return artifact_path

    def read_task_text(self, task_name: str, artifact_name: str) -> str:
        return self.read_text(self.task_artifact_path(task_name, artifact_name))

    def write_task_text(self, task_name: str, artifact_name: str, content: str) -> Path:
        self.ensure_task_dir(task_name)
        return self.write_text(self.task_artifact_path(task_name, artifact_name), content)

    def read_task_json(self, task_name: str, artifact_name: str = "state.json") -> dict[str, Any]:
        return self.read_json(self.task_artifact_path(task_name, artifact_name))

    def write_task_json(
        self,
        task_name: str,
        data: dict[str, Any],
        artifact_name: str = "state.json",
    ) -> Path:
        self.ensure_task_dir(task_name)
        return self.write_json(self.task_artifact_path(task_name, artifact_name), data)

    def write_imported_task(
        self,
        task_name: str,
        source_text: str,
        provenance: TaskSourceProvenance,
    ) -> Path:
        """Normalize text or a source task file into ``tasks/<task>/task.md``."""

        return self.write_task_text(
            task_name,
            "task.md",
            format_imported_task_markdown(source_text, provenance),
        )

    def task_state_names(self) -> tuple[str, ...]:
        """Return task names with persisted state files in deterministic order."""

        if not self.tasks_root.exists():
            return ()

        names: list[str] = []
        for state_path in self.tasks_root.glob("*/state.json"):
            task_name = state_path.parent.name
            self._validate_name(task_name, "task name")
            names.append(task_name)
        return tuple(sorted(names))

    def latest_task_name(self) -> str | None:
        """Return the latest persisted task by state write time, with stable ties."""

        candidates: list[tuple[int, str]] = []
        for task_name in self.task_state_names():
            state_path = self.task_paths(task_name).state
            candidates.append((state_path.stat().st_mtime_ns, task_name))

        if not candidates:
            return None
        return max(candidates, key=lambda item: (item[0], item[1]))[1]

    def read_task_provenance(self, task_name: str) -> TaskSourceProvenance | None:
        """Read the source metadata comment from ``task.md`` if present."""

        path = self.task_artifact_path(task_name, "task.md")
        if not path.exists():
            return None

        match = _SOURCE_PROVENANCE_RE.match(self.read_text(path))
        if match is None:
            return None

        try:
            data = json.loads(match.group("json"))
        except json.JSONDecodeError as exc:
            raise ArtifactStoreError(
                f"Task provenance metadata is invalid JSON for {task_name!r}"
            ) from exc
        return TaskSourceProvenance.from_dict(data)

    def load_task_state(self, task_name: str) -> "WorkflowState":
        """Load and validate task state, or return a safe initial state."""

        from specode.schemas import WorkflowState

        state_path = self.task_artifact_path(task_name, "state.json")
        if not state_path.exists():
            return WorkflowState.new(task_name)

        state = WorkflowState.model_validate(self.read_json(state_path))
        if state.task_name != task_name:
            raise ArtifactStoreError(
                f"State task_name {state.task_name!r} does not match task directory {task_name!r}"
            )
        return state

    def save_task_state(self, state: "WorkflowState | dict[str, Any]") -> Path:
        """Validate and persist workflow state as ``state.json``."""

        from specode.schemas import WorkflowState

        validated = WorkflowState.model_validate(state)
        return self.write_task_json(
            validated.task_name,
            validated.model_dump(mode="json"),
            "state.json",
        )

    def read_steering_text(self, doc_name: str) -> str:
        return self.read_text(self.steering_doc_path(doc_name))

    def write_steering_text(self, doc_name: str, content: str) -> Path:
        self.ensure_steering_dir()
        return self.write_text(self.steering_doc_path(doc_name), content)

    def _scoped_path(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ArtifactStoreError(
                f"Artifact path must stay inside workspace: {path}"
            ) from exc
        return resolved

    def _atomic_write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(content)
            Path(tmp_name).replace(path)
        finally:
            tmp_path = Path(tmp_name)
            if tmp_path.exists():
                tmp_path.unlink()

    def _validate_name(self, value: str, label: str) -> str:
        if not _SAFE_NAME_RE.fullmatch(value):
            raise ArtifactStoreError(
                f"{label.capitalize()} must be a simple slug without path separators: {value!r}"
            )
        return value

    def _validate_member(self, value: str, allowed: frozenset[str], label: str) -> str:
        if value not in allowed:
            allowed_values = ", ".join(sorted(allowed))
            raise ArtifactStoreError(f"Unknown {label}: {value!r}. Expected one of: {allowed_values}")
        return value


def validate_link_safe_markdown(content: str) -> None:
    """Reject Markdown links that point at absolute local filesystem paths."""

    for target in _markdown_link_targets(content):
        if _is_absolute_local_markdown_target(target):
            raise ArtifactStoreError(
                "Markdown artifacts must use relative repo links, not absolute local links: "
                f"{target}"
            )


def _markdown_link_targets(content: str) -> list[str]:
    targets: list[str] = []
    targets.extend(match.group(1) for match in _MARKDOWN_INLINE_LINK_RE.finditer(content))
    targets.extend(match.group(1) for match in _MARKDOWN_REFERENCE_LINK_RE.finditer(content))
    targets.extend(match.group(1) for match in _MARKDOWN_AUTOLINK_RE.finditer(content))
    return [unquote(target.strip("<>")) for target in targets]


def _is_absolute_local_markdown_target(target: str) -> bool:
    without_fragment = target.split("#", 1)[0]
    without_query = without_fragment.split("?", 1)[0]
    if not without_query:
        return False

    if Path(without_query).is_absolute() or PureWindowsPath(without_query).is_absolute():
        return True

    parsed = urlparse(target)
    if parsed.scheme and parsed.scheme.lower() != "file":
        return False
    if parsed.scheme.lower() == "file":
        return True
    return False


def hash_text(text: str) -> str:
    """Return a stable SHA-256 digest for source task intent."""

    return sha256(text.encode("utf-8")).hexdigest()


def format_imported_task_markdown(
    source_text: str,
    provenance: TaskSourceProvenance,
) -> str:
    """Render normalized ``task.md`` content with durable provenance."""

    metadata = json.dumps(provenance.to_dict(), indent=2, sort_keys=True)
    body = source_text.strip()
    if body:
        body = f"{body}\n"
    return (
        "<!-- specode-source\n"
        f"{metadata}\n"
        "-->\n"
        "# Task\n\n"
        "## Source Intent\n\n"
        f"{body}"
    )


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _is_default_steering_doc(doc_name: str, content: str) -> bool:
    return content.strip() == DEFAULT_STEERING_DOCS[doc_name].strip()


def _display_source_path(path: Path, workspace_root: Path) -> str:
    try:
        return path.resolve().relative_to(workspace_root.resolve()).as_posix()
    except ValueError:
        return str(path.resolve())
