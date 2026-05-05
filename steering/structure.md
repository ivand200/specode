# Structure

## Repository Shape

- `src/specode/` contains the package implementation.
- `tests/` contains behavior and contract tests; `tests/e2e/` contains integrated workflow boundary tests.
- `tests/fixtures/` contains sanitized deterministic fixtures such as mocked OpenAI runtime responses.
- `tasks/` contains SpeCode SDD task artifacts and role run records.
- `steering/` contains durable project-level guidance for future tasks, including optional focused guidance such as terminal style under `steering/style/`.
- `spec_docs/` contains copied SDD skills, agent configs, and workflow reference material.

## Entry Points

- CLI/package entry: `specode:main`, exported through `src/specode/__init__.py` and `pyproject.toml`.
- Interactive routing starts in `src/specode/cli.py` through `CommandRouter.route(...)` and `run_interactive(...)`.
- Prompt rendering and completions enter through `src/specode/interactive.py` and the pure completion helpers in `src/specode/completion.py`.
- Workflow state transitions start in `WorkflowEngine` in `src/specode/workflow.py`.
- Live OpenAI/Pydantic AI runtime entry points are `OpenAIChatRuntime` and `PydanticAgentRuntime` in `src/specode/pydantic_runtime.py`.

## Architectural Conventions

- `cli.py` classifies user input and calls workflow/runtime services; it should not own model provider details or workflow policy internals.
- `commands.py` owns canonical slash command metadata; routing, help, and completion should share that catalog instead of duplicating command lists.
- `completion.py` owns pure suggestion logic; `interactive.py` only adapts those suggestions to Prompt Toolkit.
- `workflow.py` owns deterministic SDD gates, stage routing, repair loops, and task completion decisions.
- `schemas.py` owns persisted state and role-return contracts.
- `artifacts.py` owns repo-local task and steering file access, path safety, and portable Markdown link validation.
- `runtime.py` owns stable role/chat runtime interfaces and deterministic fake runtimes.
- `pydantic_runtime.py` adapts those interfaces to Pydantic AI and OpenAI-compatible chat models.
- `ui.py` owns terminal presentation details behind a small output facade.
- `policy.py`, `workspace_tools.py`, and `execution.py` own safety decisions for files and commands.

## Module Contract

- Changes to public CLI behavior require CLI tests and, when the behavior crosses a workflow boundary, E2E coverage.
- Changes to workflow state, artifact statuses, or role routing require schema/workflow tests and careful stale-artifact behavior checks.
- Changes to role schemas require updating role runtime tests, run persistence expectations, and mocked OpenAI fixtures.
- Changes to runtime configuration require tests for defaults, missing configuration blockers, secret non-persistence, and mocked model behavior.
- File and command operations must stay behind policy-aware service boundaries; prompts should not bypass them.
- Developer, tester, and reviewer role paths share workspace-scoped tool access; role instructions guide intent, while policy and approved scope decide whether file, command, and controlled web-search operations may run.

## Module Interface Map

| Boundary | Public Interface | Hidden Details | Protected By | Deeper Review When |
| --- | --- | --- | --- | --- |
| CLI routing | `CommandRouter.route`, `RouteResult`, `specode` console script | exact output wording, helper layout, prompt loop mechanics | `tests/test_cli_router.py`, `tests/test_cli_workflow_commands.py`, E2E command tests | adding commands, changing plain-chat routing, changing `/spec`, `/run`, `@`, or `!` semantics |
| Command and completion metadata | `CommandCatalog`, `CommandDefinition`, `complete`, `FileCandidate`, prompt adapter functions | suggestion scoring, display metadata, skipped directory list, Prompt Toolkit wiring | `tests/test_commands.py`, `tests/test_completion.py`, `tests/test_interactive.py` | adding command aliases, changing completion token semantics, exposing file references, or changing reserved prefix behavior |
| Artifact storage | `ArtifactStore`, task/steering path helpers, provenance helpers | atomic write mechanics, private path normalization details | `tests/test_artifacts_store.py`, E2E artifact tests | changing artifact layout, path scope rules, provenance, or Markdown link policy |
| Workflow engine | `WorkflowEngine` transitions and `run_role_pipeline` | regex classification details, internal event strings unless asserted | workflow transition/gate/pipeline tests | changing gates, repair loops, stale artifact behavior, or manager authority |
| Role/chat runtime contracts | `AgentRuntime`, `ChatRuntime`, fake runtimes, `RoleRunResult`, `ChatResult` | fake payload construction and prompt wording | runtime and Pydantic runtime tests | changing return schemas, blocker semantics, or live/fake behavior split |
| OpenAI adapter | `PydanticRuntimeConfig`, `OpenAIChatRuntime`, `PydanticAgentRuntime` | provider construction internals, prompt assembly order, retry mechanics | `tests/test_pydantic_runtime.py`, mocked OpenAI E2E | changing env contract, model settings, structured output handling, or secret-bearing behavior |
| Run persistence | `RunStore.write_result`, `RunRecord` | run ID allocation details | `tests/test_run_store.py`, workflow pipeline tests | changing persisted schema, command/file/web summaries, blockers, or no-transcript/no-secret guarantees |
| Tool and command safety | `ToolPolicy`, `WorkspaceTools`, `LocalExecutionBackend` | concern inference internals and subprocess implementation details | policy, workspace tool, execution, and safety E2E tests | changing permission defaults, deletion behavior, command execution, env handling, or sandbox assumptions |
| Terminal UI | `TerminalUI`, `UIMessage`, and the `Printer` protocol | exact Rich styling and output wording | CLI router/workflow command tests where output is asserted | changing user-visible command output, semantic styles, or terminal style rules |

## Where To Put New Work

- New CLI commands or routing rules: `src/specode/cli.py` plus CLI and E2E tests.
- New slash command metadata or aliases: `src/specode/commands.py`; keep routing and completion behavior aligned.
- New prompt or completion behavior: pure matching in `src/specode/completion.py`, Prompt Toolkit adaptation in `src/specode/interactive.py`, and shell wiring in `src/specode/cli.py`.
- New workflow stages, gates, or repair behavior: `src/specode/workflow.py`, `src/specode/schemas.py`, and workflow tests.
- New persisted task/run data: `src/specode/schemas.py`, `src/specode/artifacts.py`, or `src/specode/run_store.py` with persistence tests; keep command, file, and web-search data compact and sanitized.
- New model/runtime behavior: `src/specode/runtime.py` for contracts and fakes, `src/specode/pydantic_runtime.py` for Pydantic AI/OpenAI integration.
- New file or shell capabilities: `src/specode/policy.py`, `src/specode/workspace_tools.py`, and `src/specode/execution.py`.
- New terminal output or presentation behavior: `src/specode/ui.py`; consult [Terminal Silver](./style/DESIGN.md) for durable style direction.
- New deterministic model examples: `tests/fixtures/` with tests that prove fixtures match current schemas.
