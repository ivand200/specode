# Tech

## Stack

- Python package with source under `src/specode/`.
- Python 3.11+ is supported; tests currently run under Python 3.13 in this workspace.
- `uv` is the expected development command runner; use `uv run ...` for project
  Python, pytest, and tooling commands instead of bare `python`/`pytest`.
- Typer owns the CLI entry point and interactive shell.
- Prompt Toolkit owns the interactive prompt adapter, history, and completions.
- Rich is used behind the small terminal UI facade for styled CLI output.
- Pydantic and Pydantic AI own schema validation and model runtime integration.
- Pytest owns unit and E2E validation.

## Key Services / Infrastructure

- Console script: `specode = "specode:main"` in `pyproject.toml`.
- Runtime config is environment based. CLI startup and live role execution prime the process environment from a workspace `.env` file when present, without overriding already-exported variables.
- Live model access uses `OpenAIChatModel` with `OpenAIProvider(api_key, base_url)` and `OpenAIChatModelSettings(openai_reasoning_effort=...)`.
- Deterministic model behavior for tests uses fake runtimes or Pydantic AI `TestModel`.
- File and command behavior is routed through `WorkspaceTools`, `LocalExecutionBackend`, and `ToolPolicy` boundaries.

## Engineering Conventions

- Keep workflow decisions deterministic; do not hide state transitions inside prompts.
- Validate untrusted role output through Pydantic schemas before routing.
- Prefer focused behavior tests for module contracts and E2E tests for workflow boundaries.
- Preserve compact run records: validated role returns, command summaries, file summaries, blockers, and notes only.
- Keep test fixtures sanitized. Mocked model fixtures must not contain real credentials or raw transcripts.
- Prefer existing modules and public interfaces over new abstraction layers.

## Related Steering Docs

- Product and workflow guidance: [Product Steering](./product.md)
- Repository boundaries and placement: [Structure Steering](./structure.md)
- Terminal/UI style guidance: [Terminal Silver](./style/DESIGN.md)
- Deep product intent: [High-Level Task](../high-level-task.md)
- Practical setup and runtime config: [README](../README.md)

## Technical Constraints

- Public env contract is `OPENAI_BASE_URL`, `CHAT_MODEL`, `OPENAI_API_KEY`, and `OPENAI_REASONING_EFFORT`.
- Defaults are `CHAT_MODEL=gpt-5.4-mini` and `OPENAI_REASONING_EFFORT=xhigh`.
- Supported broad reasoning-effort values are `none`, `minimal`, `low`, `medium`, `high`, and `xhigh`; provider/model incompatibility should become a structured blocker.
- `/run live` may make external model requests and should be explicit.
- CI and automated E2E tests must not require network access or real OpenAI credentials.
- Markdown committed to the repo should use relative links, not absolute local filesystem links.
