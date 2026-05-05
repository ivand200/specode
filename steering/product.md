# Product

## Purpose

- SpeCode is a Python CLI coding agent that combines ordinary chat with an explicit Spec-Driven Development workflow.
- The product goal is to make software work resumable, reviewable, and safer by separating chat, task specification, research/design, implementation, validation, and review.
- SpeCode should be useful in both existing repositories and empty project directories.

## Users / Actors

- Primary user: a software engineer working inside a local project directory.
- Workflow actor: the manager/state machine that owns gates, artifact freshness, routing, and completion.
- Role actors: developer, tester, and reviewer runtimes that return validated structured results.
- Future agents should treat role returns as advice until schema validation and manager routing accept them.

## Core Workflows

- Normal chat: plain text that does not start with `/`, `@`, or `!` is sent to the configured OpenAI-compatible chat runtime and must not create SDD artifacts by itself.
- Interactive assistance: the shell may suggest slash commands and workspace file-reference tokens, but completion suggestions must not change routing or create artifacts until a submitted command explicitly does so.
- SDD task start: `/spec <task description>` or `/spec <path-to-task.md>` creates or resumes `tasks/<task-name>/` artifacts.
- Steering: `/steering` creates missing `steering/product.md`, `steering/tech.md`, and `steering/structure.md`; curated steering content should remain concise and durable.
- Planning path: task -> optional research -> design -> tasks -> implementation.
- Execution path: after approval, role execution runs developer -> tester -> reviewer, with repair loops for tester failures or reviewer changes.

## Core Domain Concepts

- Task artifacts are durable records for one scoped feature, bugfix, or project request.
- Steering docs are project-level memory, not task plans or generated inventories.
- Workflow state is persisted in `state.json` and should be the source of truth for current stage, approval status, stale artifacts, blockers, and next step.
- Run records are compact validated role outputs saved under `runs/`; they are not model transcripts.
- Tool policy separates allowed, approval-needed, and denied file/command operations.

## Scope Boundaries

- `/spec` is currently deterministic workflow/artifact routing. It does not itself author full planning docs with a live model.
- Live model use is currently for ordinary chat and `/run live` role execution.
- `/run fake` remains the deterministic path for local workflow testing and CI-friendly scenarios.
- `@` and `!` prefixes are reserved; they are not implemented as file-context or shell modes yet.
- Steering should capture stable project facts only. Do not put task acceptance criteria, changelogs, rollout notes, credentials, or raw generated summaries here.

## Durable Constraints

- Planning artifacts require approval before downstream implementation.
- Stale task, design, or tasks artifacts must block implementation instead of being ignored.
- Secrets, `.env` contents, raw model transcripts, full prompts, and stdout/stderr dumps must not be persisted in task artifacts or run records.
- Public runtime configuration is OpenAI-compatible only: `OPENAI_BASE_URL`, `CHAT_MODEL`, `OPENAI_API_KEY`, and `OPENAI_REASONING_EFFORT`.
- The old `SPECODE_MODEL` and `SPECODE_MODEL_PROVIDER` env vars are ignored.
