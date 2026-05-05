from pathlib import Path

from specode.policy import ToolPolicy
from specode.workspace_tools import WorkspaceTools


def test_delete_file_asks_until_delete_is_explicitly_approved(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('keep')\n", encoding="utf-8")
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.delete_file("src/app.py", approved_scope=True)

    assert result.status == "blocked"
    assert result.policy.needs_approval
    assert result.policy.blockers[0].code == "destructive-action"
    assert target.exists()


def test_delete_file_requires_scope_when_workspace_write_policy_allows_delete(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('keep')\n", encoding="utf-8")
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.delete_file("src/app.py", approved_delete=True)

    assert result.status == "blocked"
    assert result.policy.needs_approval
    assert result.policy.required_approval == (
        "Confirm this file mutation is inside the approved task scope."
    )
    assert target.exists()


def test_delete_file_removes_file_after_explicit_policy_allow(
    tmp_path: Path,
) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('delete me')\n", encoding="utf-8")
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.delete_file(
        "src/app.py",
        approved_scope=True,
        approved_delete=True,
    )

    assert result.ok
    assert result.policy.allowed
    assert not target.exists()
    assert result.summary is not None
    assert result.summary.action == "deleted"
    assert result.summary.bytes_before == len("print('delete me')\n".encode("utf-8"))


def test_full_access_delete_still_asks_without_explicit_delete_allowance(
    tmp_path: Path,
) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("keep\n", encoding="utf-8")
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.full_access(workspace_root=tmp_path),
    )

    result = tools.delete_file("notes.txt")

    assert result.status == "blocked"
    assert result.policy.needs_approval
    assert target.exists()


def test_delete_file_does_not_delete_directories_even_when_allowed(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "src"
    directory.mkdir()
    (directory / "app.py").write_text("print('keep')\n", encoding="utf-8")
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.workspace_write(workspace_root=tmp_path),
    )

    result = tools.delete_file(
        "src",
        approved_scope=True,
        approved_delete=True,
    )

    assert result.status == "blocked"
    assert result.blocker == "delete_file only deletes files; directories are not allowed."
    assert directory.exists()
    assert (directory / "app.py").exists()


def test_reviewer_read_only_tools_cannot_mutate_files(tmp_path: Path) -> None:
    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("print('review')\n", encoding="utf-8")
    tools = WorkspaceTools(
        tmp_path,
        policy=ToolPolicy.read_only(workspace_root=tmp_path),
    )

    create = tools.create_file("src/new.py", "print('new')\n", approved_scope=True)
    update = tools.update_file("src/app.py", "print('changed')\n", approved_scope=True)
    delete = tools.delete_file(
        "src/app.py",
        approved_scope=True,
        approved_delete=True,
    )

    assert create.status == "blocked"
    assert update.status == "blocked"
    assert delete.status == "blocked"
    assert create.policy.denied
    assert update.policy.denied
    assert delete.policy.denied
    assert not (tmp_path / "src" / "new.py").exists()
    assert target.read_text(encoding="utf-8") == "print('review')\n"
