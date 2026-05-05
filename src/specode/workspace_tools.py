"""Policy-aware workspace file tools for SpeCode agents."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from specode.policy import PathOperation, PolicyDecision, ToolPolicy


ToolStatus = Literal[
    "ok",
    "blocked",
    "not_found",
    "already_exists",
    "binary",
    "error",
]


@dataclass(frozen=True)
class FileEntry:
    """A discoverable file inside the configured workspace."""

    path: str
    size_bytes: int


@dataclass(frozen=True)
class TextMatch:
    """A single text search match."""

    line_number: int
    line: str


@dataclass(frozen=True)
class SearchResult:
    """Search matches for one file."""

    path: str
    matches: tuple[TextMatch, ...]


@dataclass(frozen=True)
class MutationSummary:
    """Compact summary for a file mutation."""

    action: Literal["created", "updated", "deleted"]
    bytes_written: int
    lines_written: int
    bytes_before: int | None = None
    bytes_after: int | None = None
    changed: bool | None = None


@dataclass(frozen=True)
class WorkspaceToolResult:
    """Structured result returned by every workspace tool operation."""

    operation: str
    path: str
    status: ToolStatus
    policy: PolicyDecision
    blocker: str | None = None
    content: str | None = None
    files: tuple[FileEntry, ...] = ()
    matches: tuple[SearchResult, ...] = ()
    summary: MutationSummary | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class WorkspaceTools:
    """Discover, read, create, and update files through ToolPolicy."""

    def __init__(
        self,
        workspace_root: Path | str,
        *,
        policy: ToolPolicy | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        if policy is None:
            self.policy = ToolPolicy.read_only(workspace_root=self.workspace_root)
        elif policy.workspace_root != self.workspace_root:
            self.policy = ToolPolicy(policy.mode, workspace_root=self.workspace_root)
        else:
            self.policy = policy

    def list_files(self, path: Path | str = ".") -> WorkspaceToolResult:
        decision = self._decide("discover", path, "List workspace files.")
        result_path = decision.target_path or str(self.workspace_root / path)
        if not decision.allowed:
            return self._blocked("list_files", result_path, decision)

        target = Path(result_path)
        if not target.exists():
            return self._result("list_files", result_path, "not_found", decision)

        files: list[FileEntry] = []
        try:
            candidates = target.rglob("*") if target.is_dir() else (target,)
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve()
                if not self._inside_workspace(resolved):
                    continue
                files.append(
                    FileEntry(
                        path=self._relative_path(resolved),
                        size_bytes=resolved.stat().st_size,
                    )
                )
        except OSError as exc:
            return self._result(
                "list_files",
                result_path,
                "error",
                decision,
                blocker=str(exc),
            )

        return self._result(
            "list_files",
            result_path,
            "ok",
            decision,
            files=tuple(sorted(files, key=lambda entry: entry.path)),
        )

    def search_files(
        self,
        query: str,
        path: Path | str = ".",
        *,
        max_matches_per_file: int = 20,
    ) -> WorkspaceToolResult:
        decision = self._decide("discover", path, "Search workspace files.")
        result_path = decision.target_path or str(self.workspace_root / path)
        if not decision.allowed:
            return self._blocked("search_files", result_path, decision)
        if query == "":
            return self._result(
                "search_files",
                result_path,
                "blocked",
                decision,
                blocker="Search query must not be empty.",
            )

        target = Path(result_path)
        if not target.exists():
            return self._result("search_files", result_path, "not_found", decision)

        results: list[SearchResult] = []
        try:
            candidates = target.rglob("*") if target.is_dir() else (target,)
            for candidate in candidates:
                if not candidate.is_file():
                    continue
                resolved = candidate.resolve()
                if not self._inside_workspace(resolved) or self._looks_binary(resolved):
                    continue
                matches = self._search_text_file(
                    resolved,
                    query,
                    max_matches_per_file=max_matches_per_file,
                )
                if matches:
                    results.append(
                        SearchResult(
                            path=self._relative_path(resolved),
                            matches=tuple(matches),
                        )
                    )
        except OSError as exc:
            return self._result(
                "search_files",
                result_path,
                "error",
                decision,
                blocker=str(exc),
            )

        return self._result(
            "search_files",
            result_path,
            "ok",
            decision,
            matches=tuple(sorted(results, key=lambda result: result.path)),
        )

    def read_file(self, path: Path | str) -> WorkspaceToolResult:
        decision = self._decide("read", path, "Read workspace file.")
        result_path = decision.target_path or str(self.workspace_root / path)
        if not decision.allowed:
            return self._blocked("read_file", result_path, decision)

        target = Path(result_path)
        if not target.exists() or not target.is_file():
            return self._result("read_file", result_path, "not_found", decision)
        if self._looks_binary(target):
            return self._result(
                "read_file",
                result_path,
                "binary",
                decision,
                blocker="File appears to be binary; refusing to decode as text.",
            )

        try:
            return self._result(
                "read_file",
                result_path,
                "ok",
                decision,
                content=target.read_text(encoding="utf-8"),
            )
        except UnicodeDecodeError:
            return self._result(
                "read_file",
                result_path,
                "binary",
                decision,
                blocker="File is not valid UTF-8 text.",
            )
        except OSError as exc:
            return self._result(
                "read_file",
                result_path,
                "error",
                decision,
                blocker=str(exc),
            )

    def create_file(
        self,
        path: Path | str,
        content: str,
        *,
        approved_scope: bool = False,
    ) -> WorkspaceToolResult:
        decision = self._decide(
            "create",
            path,
            "Create workspace file.",
            approved_scope=approved_scope,
        )
        result_path = decision.target_path or str(self.workspace_root / path)
        if not decision.allowed:
            return self._blocked("create_file", result_path, decision)

        target = Path(result_path)
        if target.exists():
            return self._result("create_file", result_path, "already_exists", decision)

        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return self._result(
                "create_file",
                result_path,
                "error",
                decision,
                blocker=str(exc),
            )

        return self._result(
            "create_file",
            result_path,
            "ok",
            decision,
            summary=MutationSummary(
                action="created",
                bytes_written=len(content.encode("utf-8")),
                lines_written=_line_count(content),
                bytes_after=target.stat().st_size,
                changed=True,
            ),
        )

    def update_file(
        self,
        path: Path | str,
        content: str,
        *,
        approved_scope: bool = False,
    ) -> WorkspaceToolResult:
        decision = self._decide(
            "update",
            path,
            "Update workspace file.",
            approved_scope=approved_scope,
        )
        result_path = decision.target_path or str(self.workspace_root / path)
        if not decision.allowed:
            return self._blocked("update_file", result_path, decision)

        target = Path(result_path)
        if not target.exists() or not target.is_file():
            return self._result("update_file", result_path, "not_found", decision)
        if self._looks_binary(target):
            return self._result(
                "update_file",
                result_path,
                "binary",
                decision,
                blocker="Existing file appears to be binary; refusing text update.",
            )

        try:
            before = target.read_text(encoding="utf-8")
            before_bytes = target.stat().st_size
            target.write_text(content, encoding="utf-8")
        except UnicodeDecodeError:
            return self._result(
                "update_file",
                result_path,
                "binary",
                decision,
                blocker="Existing file is not valid UTF-8 text.",
            )
        except OSError as exc:
            return self._result(
                "update_file",
                result_path,
                "error",
                decision,
                blocker=str(exc),
            )

        return self._result(
            "update_file",
            result_path,
            "ok",
            decision,
            summary=MutationSummary(
                action="updated",
                bytes_written=len(content.encode("utf-8")),
                lines_written=_line_count(content),
                bytes_before=before_bytes,
                bytes_after=target.stat().st_size,
                changed=before != content,
            ),
        )

    def delete_file(
        self,
        path: Path | str,
        *,
        approved_scope: bool = False,
        approved_delete: bool = False,
    ) -> WorkspaceToolResult:
        decision = self._decide(
            "delete",
            path,
            "Delete workspace file.",
            approved_scope=approved_scope,
            approved_destructive=approved_delete,
        )
        result_path = decision.target_path or str(self.workspace_root / path)
        if not decision.allowed:
            return self._blocked("delete_file", result_path, decision)

        target = Path(result_path)
        if not target.exists():
            return self._result("delete_file", result_path, "not_found", decision)
        if target.is_dir():
            return self._result(
                "delete_file",
                result_path,
                "blocked",
                decision,
                blocker="delete_file only deletes files; directories are not allowed.",
            )
        if not target.is_file():
            return self._result("delete_file", result_path, "not_found", decision)

        try:
            before_bytes = target.stat().st_size
        except OSError as exc:
            return self._result(
                "delete_file",
                result_path,
                "error",
                decision,
                blocker=str(exc),
            )

        try:
            target.unlink()
        except OSError as exc:
            return self._result(
                "delete_file",
                result_path,
                "error",
                decision,
                blocker=str(exc),
            )

        return self._result(
            "delete_file",
            result_path,
            "ok",
            decision,
            summary=MutationSummary(
                action="deleted",
                bytes_written=0,
                lines_written=0,
                bytes_before=before_bytes,
                bytes_after=0,
                changed=True,
            ),
        )

    def _decide(
        self,
        operation: Literal["discover", "read", "create", "update", "delete"],
        path: Path | str,
        purpose: str,
        *,
        approved_scope: bool = False,
        approved_destructive: bool = False,
    ) -> PolicyDecision:
        return self.policy.decide_path(
            PathOperation(
                operation,
                path,
                approved_scope=approved_scope,
                approved_destructive=approved_destructive,
                purpose=purpose,
            )
        )

    def _blocked(
        self,
        operation: str,
        path: str,
        policy: PolicyDecision,
    ) -> WorkspaceToolResult:
        return self._result(
            operation,
            path,
            "blocked",
            policy,
            blocker=policy.blocker_reason or policy.required_approval or policy.reason,
        )

    def _result(
        self,
        operation: str,
        path: str,
        status: ToolStatus,
        policy: PolicyDecision,
        *,
        blocker: str | None = None,
        content: str | None = None,
        files: tuple[FileEntry, ...] = (),
        matches: tuple[SearchResult, ...] = (),
        summary: MutationSummary | None = None,
    ) -> WorkspaceToolResult:
        return WorkspaceToolResult(
            operation=operation,
            path=path,
            status=status,
            policy=policy,
            blocker=blocker,
            content=content,
            files=files,
            matches=matches,
            summary=summary,
        )

    def _inside_workspace(self, path: Path) -> bool:
        try:
            path.relative_to(self.workspace_root)
        except ValueError:
            return False
        return True

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.workspace_root).as_posix()

    @staticmethod
    def _looks_binary(path: Path) -> bool:
        try:
            sample = path.read_bytes()[:4096]
        except OSError:
            return False
        if b"\0" in sample:
            return True
        try:
            sample.decode("utf-8")
        except UnicodeDecodeError:
            return True
        return False

    @staticmethod
    def _search_text_file(
        path: Path,
        query: str,
        *,
        max_matches_per_file: int,
    ) -> list[TextMatch]:
        matches: list[TextMatch] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if query in line:
                matches.append(TextMatch(line_number=line_number, line=line))
            if len(matches) >= max_matches_per_file:
                break
        return matches


def _line_count(content: str) -> int:
    if content == "":
        return 0
    return len(content.splitlines())
