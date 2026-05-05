"""Stable reference facts used by SpeCode runtime prompts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeReference:
    """A compact source reference for runtime-facing implementation facts."""

    title: str
    url: str
    fact: str


PYDANTIC_AI_REFERENCES: tuple[RuntimeReference, ...] = (
    RuntimeReference(
        title="Pydantic AI structured output",
        url="https://pydantic.dev/docs/ai/core-concepts/output/",
        fact=(
            "Agent(..., output_type=...) validates model-returned structured "
            "data against the declared output type."
        ),
    ),
    RuntimeReference(
        title="Pydantic AI testing",
        url="https://pydantic.dev/docs/ai/guides/testing/",
        fact=(
            "Use TestModel or FunctionModel with Agent.override(...) to test "
            "agent code without live model calls."
        ),
    ),
    RuntimeReference(
        title="Pydantic AI OpenAI chat models",
        url="https://pydantic.dev/docs/ai/models/openai/",
        fact=(
            "OpenAIChatModel can be constructed with an OpenAIProvider carrying "
            "API key and base URL configuration."
        ),
    ),
    RuntimeReference(
        title="OpenAI reasoning effort",
        url="https://platform.openai.com/docs/api-reference/chat/create-chat-completion",
        fact=(
            "OpenAI reasoning effort is a model setting with supported values "
            "including none, minimal, low, medium, high, and xhigh."
        ),
    ),
)


ROLE_RUNTIME_INSTRUCTIONS: dict[str, str] = {
    "developer": (
        "You are the SpeCode developer role. Implement only approved scope, "
        "use workspace-scoped file, command, and controlled web_search tools "
        "only through SpeCode policy, honor approved or yolo automation policy, "
        "and return the validated Task Return structure."
    ),
    "tester": (
        "You are the SpeCode tester role. Validate accepted artifacts and the "
        "developer return, create or edit tests when workspace-scoped policy "
        "allows it, route validation commands through the execution backend, "
        "use controlled web_search only when needed, and return the validated "
        "Validation Return structure."
    ),
    "reviewer": (
        "You are the SpeCode reviewer role. Review against accepted artifacts "
        "and role returns, use the same workspace-scoped file, command, and "
        "controlled web_search tools as other roles, fix small clear issues "
        "when policy and approved scope allow it, and return the validated "
        "Review Return structure."
    ),
}
