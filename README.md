# SpeCode

SpeCode is an opinionated Python CLI coding agent with an explicit Spec-Driven Development workflow. It behaves like a normal chat-based coding assistant by default, and enters durable SDD mode only when you use `/spec`.

## What SpeCode Does

- Routes ordinary text to the configured OpenAI-compatible chat model.
- Uses `/spec` to create resumable task artifacts under `tasks/<task-name>/`.
- Uses `/steering` to scan the repository and create durable project context under `steering/`.
- Drives approved work through `developer -> tester -> reviewer` role execution.
- Persists compact role run records under `tasks/<task-name>/runs/`.
- Keeps automated tests deterministic with fake or mocked model responses.

## Requirements

- Python 3.11 or newer.
- `uv` for local development, test commands, and the recommended one-shot run path.
- `git` when installing directly from GitHub.
- An OpenAI-compatible API key for live chat or live role execution.

## Quick Start

Run SpeCode directly from GitHub without cloning the repository:

```bash
uvx --from git+https://github.com/ivand200/specode.git specode
```

For live chat, provide runtime configuration first:

```bash
export OPENAI_API_KEY=...
export CHAT_MODEL=gpt-5.4-mini
export OPENAI_REASONING_EFFORT=xhigh
uvx --from git+https://github.com/ivand200/specode.git specode
```

To work on SpeCode locally:

```bash
git clone https://github.com/ivand200/specode.git
cd specode
uv sync
uv run specode
```

## Install From GitHub

Use one of these options depending on how you want to run the CLI.

One-shot run with `uvx`:

```bash
uvx --from git+https://github.com/ivand200/specode.git specode
```

Install as a persistent CLI tool with `uv`:

```bash
uv tool install git+https://github.com/ivand200/specode.git
specode
```

Install in an isolated tool environment with `pipx`:

```bash
pipx install git+https://github.com/ivand200/specode.git
specode
```

Install from a local clone for development:

```bash
uv sync
uv run specode
```

Upgrade a persistent `uv` tool install:

```bash
uv tool upgrade specode
```

If you installed with `pipx`, upgrade with:

```bash
pipx upgrade specode
```

## Run SpeCode

From an installed CLI:

```bash
specode
```

From a local clone:

```bash
uv run specode
```

Run tests from a local clone:

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

- `OPENAI_API_KEY` is required for live chat and live role execution.
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
/exit
/quit
```

Routing rules:

- Plain input that does not start with `/`, `@`, or `!` is normal chat.
- Public `/` commands are reserved for session and mode switches only.
- `@` and `!` are reserved for future explicit file-context and shell-command modes, and are not silently sent to chat.
- `/steering` scans local repository evidence such as README files, package manifests, entry points, source directories, and tests before writing missing/default steering docs.
- Approval, revision, status, cancellation, and role execution are manager workflow intents, not public slash commands.

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

## Usage Best Practices

- Start with plain chat for quick questions, code explanation, and brainstorming.
- Use `/spec` when the work should leave a durable trail: features, bugfixes, project setup, workflow changes, or anything that needs review.
- Keep `/steering` focused on stable project facts. Put task-specific decisions in `tasks/<task-name>/`, not in steering docs.
- Approve planning artifacts before running implementation. Stale artifacts should be revised before work continues.
- Use normal chat to ask for status, approval, revision, cancellation, or implementation.
- Review `tasks/<task-name>/state.json` when resuming work after a break.

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
- Prefer shell environment variables or an uncommitted workspace `.env` file for secrets.
- Use `.env.example` for documented, non-secret configuration names and defaults.
- Let exported environment variables override `.env` when running in CI or shared shells.
- Prefer fake runtimes and mocked tests for routine validation.
- Use live role execution only when you intentionally want external model calls.
- Keep file, command, and controlled web-search operations behind SpeCode policy/runtime boundaries.
- Treat file deletion and destructive commands as high-risk operations.
- Use reviewer edits only for small clear issues inside the approved workspace scope.
- Keep artifacts current; stale task, design, or tasks artifacts should block implementation.
- Do not store raw model transcripts in task artifacts or run records.

## Development Best Practices

- Follow existing module boundaries before adding abstractions.
- Use `uv run ...` for project Python commands so tests and local runs use the locked environment.
- Keep workflow routing deterministic; model outputs are advice after schema validation.
- Add behavior tests around public contracts and workflow transitions.
- Use E2E tests for major workflow boundaries.
- Keep mocked model fixtures sanitized and deterministic.
- Prefer focused tests while editing, then run the full suite before handoff.
- Keep Markdown links relative so repository docs work after cloning.

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
