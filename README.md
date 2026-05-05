# SpeCode

SpeCode is an opinionated Python CLI coding agent with an explicit Spec-Driven Development workflow. It behaves like a normal chat-based coding assistant by default, and enters durable SDD mode only when you use `/spec`.

## What SpeCode Does

- Routes ordinary text to the configured OpenAI-compatible chat model.
- Uses `/spec` to create resumable task artifacts under `tasks/<task-name>/`.
- Uses `/steering` to create durable project context under `steering/`.
- Drives approved work through `developer -> tester -> reviewer` role execution.
- Persists compact role run records under `tasks/<task-name>/runs/`.
- Keeps automated tests deterministic with fake or mocked model responses.

## Requirements

- Python 3.11 or newer.
- `uv` for environment and test commands.
- An OpenAI-compatible API key for live chat or live role execution.

## Install

From the repo root:

```bash
uv sync
```

Run the CLI in development:

```bash
uv run specode
```

Run tests:

```bash
uv run pytest
```

## Runtime Configuration

SpeCode's public model configuration contract is `.env.example`:

```dotenv
OPENAI_BASE_URL=
CHAT_MODEL=gpt-5.4-mini
OPENAI_API_KEY=
OPENAI_REASONING_EFFORT=xhigh
```

Configuration notes:

- `OPENAI_API_KEY` is required for live chat and `/run live`.
- `CHAT_MODEL` defaults to `gpt-5.4-mini` when unset.
- `OPENAI_REASONING_EFFORT` defaults to `xhigh` when unset.
- Supported reasoning-effort values are `none`, `minimal`, `low`, `medium`, `high`, and `xhigh`; actual model compatibility is provider-specific.
- `OPENAI_BASE_URL` is optional and supports OpenAI-compatible endpoints.
- `SPECODE_MODEL` and `SPECODE_MODEL_PROVIDER` are ignored.
- SpeCode loads `.env` from the current workspace at CLI startup, then reads the
  process environment. Already-exported variables take precedence over `.env`.
- Missing live-runtime configuration is reported immediately when the shell
  starts, before the first chat message is submitted.

Example:

```bash
export OPENAI_API_KEY=...
export CHAT_MODEL=gpt-5.4-mini
export OPENAI_REASONING_EFFORT=xhigh
uv run specode
```

## CLI Commands

```text
/spec <task description>
/spec <path-to-task.md>
/steering
/status
/approve
/revise <instruction>
/cancel [reason]
/run fake
/run live
/exit
```

Routing rules:

- Plain input that does not start with `/`, `@`, or `!` is normal chat.
- `/` commands are workflow/meta controls.
- `@` and `!` are reserved for future explicit file-context and shell-command modes, and are not silently sent to chat.
- `/run fake` uses deterministic fake role returns.
- `/run live` uses the OpenAI/Pydantic runtime and may make real model requests.
  Live role runs carry an explicit automation policy: `approved` executes only
  policy-allowed operations, while `yolo` is reserved for approved workspace
  automation with separate safety gates.

## SDD Workflow

The V0 workflow is:

```text
task -> research optional -> design -> tasks -> implementation -> testing -> review -> done
```

Artifact layout:

```text
tasks/<task-name>/
  state.json
  task.md
  context.md        # when research is required
  design.md
  tasks.md
  runs/
    0001-developer.json
    0002-tester.json
    0003-reviewer.json
```

Rules of thumb:

- Use normal chat for questions, explanations, brainstorming, and small no-artifact help.
- Use `/spec` for feature work, bugfixes, greenfield project work, or anything that should be resumable and reviewed.
- Approve each planning gate before implementation.
- If a task crosses architecture, data, auth, external APIs, security, privacy, performance, or operational risk, insert research before design.
- If scope changes during implementation, mark artifacts stale and return to the right planning stage instead of silently continuing.

## Role Runtime

SpeCode has three structured role returns:

- `developer`: returns `ready_for_testing`, `needs_split`, or `blocked`.
- `tester`: returns `pass`, `fail`, or `blocked`.
- `reviewer`: returns `pass`, `changes_requested`, or `blocked`.

All role outputs are validated through Pydantic schemas before workflow routing. Malformed model output becomes a structured blocked result and does not advance the workflow.

Developer, tester, and reviewer roles share the same workspace-scoped access model. Role instructions guide intent: developer implements, tester validates and may adjust tests, and reviewer reviews first but may fix small clear issues when policy and approved scope allow it. File operations, command execution, and controlled `web_search` must still route through SpeCode policy/runtime boundaries.

Run records persist only validated role returns, compact command summaries, compact file summaries, compact web-search summaries, blockers, and notes. They must not contain API keys, raw transcripts, full prompts, stdout/stderr dumps, raw web pages, or `.env` contents.

## Safety And Privacy Best Practices

- Do not commit `.env` or real credentials.
- Keep secrets in process environment only.
- Use `.env.example` for documented configuration.
- Prefer `/run fake` and mocked tests for routine validation.
- Use `/run live` only when you intentionally want external model calls.
- Keep file, command, and controlled web-search operations behind SpeCode policy/runtime boundaries.
- Treat file deletion and destructive commands as high-risk operations.
- Use reviewer edits only for small clear issues inside the approved workspace scope.
- Keep artifacts current; stale task, design, or tasks artifacts should block implementation.
- Do not store raw model transcripts in task artifacts or run records.

## Development Best Practices

- Follow existing module boundaries before adding abstractions.
- Keep workflow routing deterministic; model outputs are advice after schema validation.
- Add behavior tests around public contracts and workflow transitions.
- Use E2E tests for major workflow boundaries.
- Keep mocked model fixtures sanitized and deterministic.
- Prefer focused tests while editing, then run the full suite before handoff.

Useful commands:

```bash
uv run pytest tests/test_pydantic_runtime.py
uv run pytest tests/test_cli_router.py
uv run pytest tests/test_workflow_pipeline.py
uv run pytest tests/e2e/test_openai_chatgpt_runtime.py
uv run pytest
```

## Project Structure

```text
src/specode/
  cli.py                # Typer CLI and command routing
  pydantic_runtime.py   # OpenAI/Pydantic AI runtime adapters
  runtime.py            # role/chat runtime contracts and fakes
  workflow.py           # deterministic SDD workflow state machine
  schemas.py            # Pydantic state and role-return schemas
  run_store.py          # compact role run persistence
  artifacts.py          # task and steering artifact storage
  policy.py             # tool policy decisions
  workspace_tools.py    # policy-aware file operations
  execution.py          # policy-aware command execution
tests/
  e2e/                  # integrated workflow boundary tests
  fixtures/             # sanitized mocked model fixtures
tasks/
  <task-name>/          # SpeCode SDD task artifacts
steering/
  product.md
  tech.md
  structure.md
```

## References

- Product and workflow intent: [high-level-task.md](./high-level-task.md)
- SDD skills and agents: [spec_docs/README.md](./spec_docs/README.md)
- Research links: [references.md](./references.md)
- OpenAI runtime task: [tasks/openai-chatgpt-runtime](./tasks/openai-chatgpt-runtime)
