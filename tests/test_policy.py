from pathlib import Path

from specode.policy import CommandOperation, PathOperation, ToolPolicy


def test_policy_defaults_to_read_only_and_does_not_grant_full_access() -> None:
    policy = ToolPolicy()

    decision = policy.decide_path(PathOperation("update", "src/app.py"))

    assert policy.mode == "read-only"
    assert decision.denied
    assert decision.blockers[0].code == "read-only-mutation"


def test_read_only_allows_workspace_file_reads(tmp_path: Path) -> None:
    policy = ToolPolicy.read_only(workspace_root=tmp_path)

    decision = policy.decide_path(PathOperation("read", "README.md"))

    assert decision.allowed
    assert decision.target_path == str(tmp_path / "README.md")


def test_read_only_denies_file_mutations_with_structured_reason(
    tmp_path: Path,
) -> None:
    policy = ToolPolicy.read_only(workspace_root=tmp_path)

    decision = policy.decide_path(PathOperation("create", "src/new_file.py"))

    assert decision.denied
    assert decision.reason == "create is not allowed while policy mode is read-only."
    assert decision.blocker_reason == decision.reason


def test_workspace_write_allows_approved_scope_create_and_update(
    tmp_path: Path,
) -> None:
    policy = ToolPolicy.workspace_write(workspace_root=tmp_path)

    create = policy.decide_path(
        PathOperation("create", "src/new_file.py", approved_scope=True)
    )
    update = policy.decide_path(
        PathOperation("update", "src/existing.py", approved_scope=True)
    )

    assert create.allowed
    assert update.allowed


def test_workspace_write_asks_before_unapproved_mutation(tmp_path: Path) -> None:
    policy = ToolPolicy.workspace_write(workspace_root=tmp_path)

    decision = policy.decide_path(PathOperation("update", "src/app.py"))

    assert decision.needs_approval
    assert decision.required_approval == (
        "Confirm this file mutation is inside the approved task scope."
    )


def test_deletion_denies_in_read_only_and_asks_in_write_modes(
    tmp_path: Path,
) -> None:
    read_only = ToolPolicy.read_only(workspace_root=tmp_path)
    workspace_write = ToolPolicy.workspace_write(workspace_root=tmp_path)
    full_access = ToolPolicy.full_access(workspace_root=tmp_path)

    denied = read_only.decide_path(PathOperation("delete", "src/app.py"))
    asks_workspace = workspace_write.decide_path(PathOperation("delete", "src/app.py"))
    asks_full = full_access.decide_path(PathOperation("delete", "src/app.py"))

    assert denied.denied
    assert asks_workspace.needs_approval
    assert asks_full.needs_approval
    assert asks_full.blockers[0].code == "destructive-action"


def test_paths_outside_workspace_are_denied_before_mode_rules(
    tmp_path: Path,
) -> None:
    policy = ToolPolicy.full_access(workspace_root=tmp_path)

    decision = policy.decide_path(PathOperation("read", tmp_path.parent / "secret.txt"))

    assert decision.denied
    assert decision.blockers[0].code == "outside-workspace"


def test_read_only_denies_mutating_commands() -> None:
    policy = ToolPolicy.read_only()

    decision = policy.decide_command(CommandOperation.from_argv(["git", "commit"]))

    assert decision.denied
    assert decision.blockers[0].code == "read-only-command-mutation"
    assert "mutates_state" in decision.concerns


def test_workspace_write_asks_for_network_dependency_commands() -> None:
    policy = ToolPolicy.workspace_write()

    decision = policy.decide_command(CommandOperation.from_argv(["uv", "add", "rich"]))

    assert decision.needs_approval
    assert {"network", "installs_dependencies", "mutates_state"} <= decision.concerns
    assert decision.required_approval is not None


def test_full_access_allows_broader_non_destructive_commands() -> None:
    policy = ToolPolicy.full_access()

    decision = policy.decide_command(CommandOperation.from_argv(["git", "pull"]))

    assert decision.allowed
    assert "network" in decision.concerns


def test_full_access_still_denies_destructive_credential_and_unsafe_commands() -> None:
    policy = ToolPolicy.full_access()

    destructive = policy.decide_command(CommandOperation.from_argv(["rm", "-rf", "src"]))
    credential = policy.decide_command(
        CommandOperation.from_argv(["aws", "s3", "ls"])
    )
    unsafe = policy.decide_command(
        CommandOperation.from_argv(["bash", "-c", "rm -rf src"])
    )

    assert destructive.denied
    assert credential.denied
    assert unsafe.denied
    assert {destructive.blockers[0].code, credential.blockers[0].code, unsafe.blockers[0].code} == {
        "destructive-command",
        "credentials-required",
        "unsafe-command",
    }


def test_explicit_blockers_override_other_command_policy() -> None:
    policy = ToolPolicy.full_access()

    decision = policy.decide_command(
        CommandOperation.from_argv(
            ["pytest"],
            explicit_blocker="Required service credentials are missing.",
        )
    )

    assert decision.denied
    assert decision.blocker_reason == "Required service credentials are missing."
