"""Controlled web-search boundary for SpeCode role tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence
from urllib.parse import quote_plus, urlparse

from specode.tool_sanitizer import (
    MAX_WEB_QUERY_CHARS,
    MAX_WEB_RESULTS,
    MAX_WEB_SNIPPET_CHARS,
    MAX_WEB_TITLE_CHARS,
    SanitizedText,
    sanitize_text,
)


WebSearchStatus = Literal["ok", "blocked", "error"]


@dataclass(frozen=True)
class WebSearchRequest:
    """A bounded search request accepted by SpeCode-controlled backends."""

    query: str
    max_results: int = MAX_WEB_RESULTS
    allowed_domains: tuple[str, ...] = ()
    query_capped: bool = field(init=False, default=False)
    query_redacted: bool = field(init=False, default=False)
    max_results_capped: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        query = sanitize_text(str(self.query), max_chars=MAX_WEB_QUERY_CHARS)
        requested_results = int(self.max_results)
        normalized_max = max(1, min(requested_results, MAX_WEB_RESULTS))
        domains = tuple(
            domain.strip().lower()
            for domain in self.allowed_domains
            if domain.strip()
        )

        object.__setattr__(self, "query", query.text.strip())
        object.__setattr__(self, "max_results", normalized_max)
        object.__setattr__(self, "allowed_domains", domains)
        object.__setattr__(self, "query_capped", query.capped)
        object.__setattr__(self, "query_redacted", query.redacted)
        object.__setattr__(
            self,
            "max_results_capped",
            requested_results != normalized_max,
        )

    @property
    def capped(self) -> bool:
        return self.query_capped or self.max_results_capped


@dataclass(frozen=True)
class WebSearchResult:
    """Source metadata returned from a controlled web search."""

    title: str
    url: str
    snippet: str
    capped: bool = field(init=False, default=False)
    redacted: bool = field(init=False, default=False)

    def __post_init__(self) -> None:
        title = sanitize_text(str(self.title), max_chars=MAX_WEB_TITLE_CHARS)
        snippet = sanitize_text(str(self.snippet), max_chars=MAX_WEB_SNIPPET_CHARS)
        object.__setattr__(self, "title", title.text)
        object.__setattr__(self, "url", str(self.url))
        object.__setattr__(self, "snippet", snippet.text)
        object.__setattr__(self, "capped", title.capped or snippet.capped)
        object.__setattr__(self, "redacted", title.redacted or snippet.redacted)


@dataclass(frozen=True)
class WebSearchSummary:
    """Compact durable metadata for one search call."""

    query: str
    status: WebSearchStatus
    result_count: int
    urls: tuple[str, ...] = ()
    backend: str = "unknown"
    blocker: str | None = None
    kind: Literal["web_search"] = "web_search"


@dataclass(frozen=True)
class WebSearchResponse:
    """Structured response returned by every web-search backend."""

    query: str
    status: WebSearchStatus
    results: tuple[WebSearchResult, ...] = ()
    backend: str = "unknown"
    capped: bool = False
    blocker: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def summary(self) -> WebSearchSummary:
        return WebSearchSummary(
            query=self.query,
            status=self.status,
            result_count=len(self.results),
            urls=tuple(result.url for result in self.results),
            backend=self.backend,
            blocker=self.blocker,
        )


class WebSearchBackend(ABC):
    """Abstract boundary for controlled source-metadata web search."""

    @abstractmethod
    def search(self, request: WebSearchRequest) -> WebSearchResponse:
        """Search without arbitrary page fetches."""


class BlockedWebSearchBackend(WebSearchBackend):
    """Backend used when live web search is disabled or unconfigured."""

    def __init__(
        self,
        *,
        backend: str = "unconfigured",
        blocker: str = "Web search backend is not configured.",
    ) -> None:
        self.backend = backend
        self.blocker = blocker

    def search(self, request: WebSearchRequest) -> WebSearchResponse:
        return WebSearchResponse(
            query=request.query,
            status="blocked",
            results=(),
            backend=self.backend,
            capped=request.capped,
            blocker=self.blocker,
        )


class UnconfiguredWebSearchBackend(BlockedWebSearchBackend):
    """Named blocked backend for the default live configuration."""


class FakeWebSearchBackend(WebSearchBackend):
    """Deterministic in-memory web-search backend for tests and E2E paths."""

    def __init__(
        self,
        results_by_query: Mapping[str, Sequence[WebSearchResult | Mapping[str, str]]]
        | None = None,
        *,
        backend: str = "fake",
    ) -> None:
        self.backend = backend
        self._results_by_query = {
            str(query): tuple(_coerce_result(result) for result in results)
            for query, results in (results_by_query or {}).items()
        }

    def search(self, request: WebSearchRequest) -> WebSearchResponse:
        if not request.query:
            return WebSearchResponse(
                query=request.query,
                status="blocked",
                backend=self.backend,
                capped=request.capped,
                blocker="Search query must not be empty.",
            )

        candidates = self._results_by_query.get(request.query)
        if candidates is None:
            candidates = (_default_result(request.query),)

        filtered = tuple(
            result
            for result in candidates
            if _domain_allowed(result.url, request.allowed_domains)
        )
        selected = filtered[: request.max_results]
        capped = (
            request.capped
            or len(filtered) > len(selected)
            or any(result.capped or result.redacted for result in selected)
        )
        return WebSearchResponse(
            query=request.query,
            status="ok",
            results=selected,
            backend=self.backend,
            capped=capped,
        )


def search_web(
    backend: WebSearchBackend,
    query: str,
    *,
    max_results: int = MAX_WEB_RESULTS,
    allowed_domains: Sequence[str] = (),
) -> WebSearchResponse:
    """Convenience wrapper that builds a capped request before searching."""

    return backend.search(
        WebSearchRequest(
            query=query,
            max_results=max_results,
            allowed_domains=tuple(allowed_domains),
        )
    )


def _coerce_result(result: WebSearchResult | Mapping[str, str]) -> WebSearchResult:
    if isinstance(result, WebSearchResult):
        return result
    return WebSearchResult(
        title=result.get("title", ""),
        url=result.get("url", ""),
        snippet=result.get("snippet", ""),
    )


def _default_result(query: str) -> WebSearchResult:
    return WebSearchResult(
        title=f"Fake result for {query}",
        url=f"https://example.test/search?q={quote_plus(query)}",
        snippet=f"Deterministic fake search result for {query}.",
    )


def _domain_allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    if not allowed_domains:
        return True
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)
