from pathlib import Path

from specode.policy import ToolPolicy
from specode.workspace_tools import WorkspaceTools


def test_read_only_discovers_and_reads_workspace_text_files(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("print('hello')\n", encoding="utf-8")
    tools = WorkspaceTools(tmp_path, policy=ToolPolicy.read_only(workspace_root=tmp_path))

    listing = tools.list_files()
    read = tools.read_file("src/app.py")

    assert listing.ok and listing.files[0].path == "src/app.py"
    assert read.ok and read.content == "print('hello')\n"


def test_search_files_returns_text_matches_and_skips_binary_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.md").write_text("alpha\nbeta alpha\n", encoding="utf-8")
    (tmp_path / "blob.bin").write_bytes(b"alpha\x00beta")
    tools = WorkspaceTools(tmp_path, policy=ToolPolicy.read_only(workspace_root=tmp_path))

    result = tools.search_files("alpha")

    assert result.ok
    assert [(match.path, len(match.matches)) for match in result.matches] == [
        ("notes.md", 2)
    ]


def test_read_file_refuses_binary_content_conservatively(tmp_path: Path) -> None:
    (tmp_path / "image.bin").write_bytes(b"\x89PNG\x00payload")
    tools = WorkspaceTools(tmp_path, policy=ToolPolicy.read_only(workspace_root=tmp_path))

    result = tools.read_file("image.bin")

    assert result.status == "binary"
    assert result.content is None


def test_read_only_blocks_create_and_reports_policy_context(tmp_path: Path) -> None:
    tools = WorkspaceTools(tmp_path, policy=ToolPolicy.read_only(workspace_root=tmp_path))

    result = tools.create_file("src/new.py", "print('new')\n", approved_scope=True)

    assert result.status == "blocked"
    assert result.policy.denied and result.blocker == result.policy.blocker_reason


def test_workspace_write_requires_approved_scope_for_mutations(
    tmp_path: Path,
) -> None:
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.create_file("src/new.py", "print('new')\n")

    assert result.status == "blocked"
    assert result.policy.needs_approval


def test_create_file_writes_inside_workspace_with_mutation_summary(
    tmp_path: Path,
) -> None:
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.create_file("src/new.py", "print('new')\n", approved_scope=True)

    assert result.ok and (tmp_path / "src" / "new.py").read_text() == "print('new')\n"
    assert result.summary is not None and result.summary.action == "created"


def test_update_file_writes_text_and_reports_changed_summary(tmp_path: Path) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("old\n", encoding="utf-8")
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.update_file("src/app.py", "new\n", approved_scope=True)

    assert result.ok and target.read_text(encoding="utf-8") == "new\n"
    assert result.summary is not None and result.summary.changed is True


def test_update_file_refuses_existing_binary_file(tmp_path: Path) -> None:
    (tmp_path / "data.bin").write_bytes(b"old\x00data")
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.update_file("data.bin", "new text\n", approved_scope=True)

    assert result.status == "binary"
    assert (tmp_path / "data.bin").read_bytes() == b"old\x00data"


def test_out_of_workspace_paths_block_before_filesystem_access(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / "outside.txt"
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.read_file(outside)

    assert result.status == "blocked"
    assert result.policy.blockers[0].code == "outside-workspace"


def test_results_expose_operation_path_status_policy_and_blocker(
    tmp_path: Path,
) -> None:
    tools = WorkspaceTools(tmp_path, policy=ToolPolicy.read_only(workspace_root=tmp_path))

    result = tools.update_file("missing.py", "", approved_scope=True)

    assert (result.operation, result.status, result.path) == (
        "update_file",
        "blocked",
        str(tmp_path / "missing.py"),
    )
    assert result.policy.operation == "update" and result.blocker is not None
