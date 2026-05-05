from __future__ import annotations

from specode.tool_sanitizer import (
    MAX_WEB_QUERY_CHARS,
    MAX_WEB_RESULTS,
    MAX_WEB_SNIPPET_CHARS,
    MAX_WEB_TITLE_CHARS,
)
from specode.web_search import (
    BlockedWebSearchBackend,
    FakeWebSearchBackend,
    WebSearchRequest,
    WebSearchResult,
    search_web,
)


def test_fake_backend_returns_deterministic_default_result() -> None:
    response = search_web(FakeWebSearchBackend(), "line windows")

    assert response.ok
    assert response.backend == "fake"
    assert response.results[0].title == "Fake result for line windows"
    assert response.results[0].url == "https://example.test/search?q=line+windows"


def test_fake_backend_uses_configured_results_and_caps_count() -> None:
    backend = FakeWebSearchBackend(
        {
            "specode": [
                {
                    "title": f"Result {index}",
                    "url": f"https://docs.example/{index}",
                    "snippet": "snippet",
                }
                for index in range(MAX_WEB_RESULTS + 2)
            ]
        }
    )

    response = search_web(backend, "specode", max_results=MAX_WEB_RESULTS + 20)

    assert response.ok
    assert len(response.results) == MAX_WEB_RESULTS
    assert response.capped
    assert response.summary.result_count == MAX_WEB_RESULTS
    assert response.summary.urls[0] == "https://docs.example/0"


def test_request_caps_query_and_normalizes_domains() -> None:
    request = WebSearchRequest(
        "x" * (MAX_WEB_QUERY_CHARS + 20),
        max_results=MAX_WEB_RESULTS + 1,
        allowed_domains=(" Example.COM ", ""),
    )

    assert len(request.query) == MAX_WEB_QUERY_CHARS
    assert request.max_results == MAX_WEB_RESULTS
    assert request.allowed_domains == ("example.com",)
    assert request.capped


def test_results_cap_title_and_snippet_and_redact_secret_lines() -> None:
    result = WebSearchResult(
        title="T" * (MAX_WEB_TITLE_CHARS + 1),
        url="https://example.com",
        snippet="safe\npassword = leaked\n" + "S" * (MAX_WEB_SNIPPET_CHARS + 10),
    )

    assert len(result.title) == MAX_WEB_TITLE_CHARS
    assert "leaked" not in result.snippet
    assert len(result.snippet) == MAX_WEB_SNIPPET_CHARS
    assert result.capped
    assert result.redacted


def test_blocked_backend_returns_unconfigured_blocker_without_results() -> None:
    response = search_web(BlockedWebSearchBackend(), "current docs")

    assert response.status == "blocked"
    assert response.results == ()
    assert response.blocker == "Web search backend is not configured."
    assert response.summary.backend == "unconfigured"


def test_empty_query_is_blocked_by_fake_backend() -> None:
    response = search_web(FakeWebSearchBackend(), "   ")

    assert response.status == "blocked"
    assert response.blocker == "Search query must not be empty."


def test_allowed_domains_filter_results() -> None:
    backend = FakeWebSearchBackend(
        {
            "docs": [
                {
                    "title": "Allowed",
                    "url": "https://docs.example.com/a",
                    "snippet": "kept",
                },
                {
                    "title": "Blocked",
                    "url": "https://other.example/b",
                    "snippet": "filtered",
                },
            ]
        }
    )

    response = search_web(backend, "docs", allowed_domains=("example.com",))

    assert [result.title for result in response.results] == ["Allowed"]
