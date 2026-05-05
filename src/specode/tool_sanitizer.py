"""Shared caps and redaction helpers for model-visible tool output."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path


DEFAULT_FILE_LINE_LIMIT = 200
MAX_FILE_LINE_LIMIT = 2_000
MAX_FILE_CHARS = 80_000
MAX_LIST_FILES = 200
MAX_SEARCH_FILES = 50
MAX_MATCHES_PER_FILE = 5
MAX_MATCH_LINE_CHARS = 500
MAX_COMMAND_OUTPUT_CHARS = 8_000
MAX_WEB_QUERY_CHARS = 300
MAX_WEB_RESULTS = 5
MAX_WEB_TITLE_CHARS = 200
MAX_WEB_SNIPPET_CHARS = 1_000

SECRET_LINE_REPLACEMENT = "[REDACTED]"

_SECRET_MARKER_RE = re.compile(
    r"\b("
    r"api[_-]?key|apikey|"
    r"(?:access|auth|refresh|session)?[_-]?token|"
    r"password|passwd|secret|private[_-]?key|credential"
    r")s?\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SanitizedText:
    """Text plus metadata describing model-visible safety changes."""

    text: str
    capped: bool = False
    redacted: bool = False


@dataclass(frozen=True)
class LineWindow:
    """A bounded line range selected from sanitized text."""

    content: str
    start_line: int
    end_line: int
    total_lines: int
    has_more: bool
    next_start_line: int | None
    capped: bool
    redacted: bool
    requested_limit: int
    effective_limit: int

    def as_metadata(self) -> dict[str, int | bool | None]:
        return {
            "start_line": self.start_line,
            "end_line": self.end_line,
            "total_lines": self.total_lines,
            "has_more": self.has_more,
            "next_start_line": self.next_start_line,
            "capped": self.capped,
            "redacted": self.redacted,
            "requested_limit": self.requested_limit,
            "effective_limit": self.effective_limit,
        }


class SecretFileError(ValueError):
    """Raised when model-visible file content must be blocked entirely."""


class BinaryContentError(ValueError):
    """Raised when arbitrary bytes should not be decoded for the model."""


def is_secret_file_path(path: str | Path) -> bool:
    """Return whether a path is a blocked env-style secret file."""

    name = Path(path).name.lower()
    if name == ".env.example":
        return False
    return name == ".env" or fnmatch.fnmatch(name, "*.env.*")


def looks_binary_bytes(content: bytes) -> bool:
    """Conservatively classify bytes that should not be exposed as text."""

    if b"\x00" in content:
        return True
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def decode_text_content(content: str | bytes, *, path: str | Path | None = None) -> str:
    """Decode trusted text input after blocking secret paths and binary bytes."""

    if path is not None and is_secret_file_path(path):
        raise SecretFileError("Refusing to expose env-style secret file content.")
    if isinstance(content, str):
        return content
    if looks_binary_bytes(content):
        raise BinaryContentError("Refusing to expose arbitrary binary content.")
    return content.decode("utf-8")


def contains_secret_marker(line: str) -> bool:
    """Return whether one line contains an obvious secret-bearing marker."""

    return _SECRET_MARKER_RE.search(line) is not None


def redact_secret_lines(text: str) -> SanitizedText:
    """Replace obvious secret-bearing lines while preserving line endings."""

    redacted = False
    safe_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        if contains_secret_marker(line):
            redacted = True
            safe_lines.append(SECRET_LINE_REPLACEMENT + _line_ending(line))
        else:
            safe_lines.append(line)

    if text and not safe_lines:
        return SanitizedText(text, redacted=False)
    return SanitizedText("".join(safe_lines), redacted=redacted)


def cap_text(text: str, max_chars: int) -> SanitizedText:
    """Cap text to an exact maximum character count."""

    if max_chars < 0:
        raise ValueError("max_chars must not be negative")
    if len(text) <= max_chars:
        return SanitizedText(text)
    return SanitizedText(text[:max_chars], capped=True)


def sanitize_text(text: str, *, max_chars: int) -> SanitizedText:
    """Redact secret-like lines and cap the resulting text."""

    redacted = redact_secret_lines(text)
    capped = cap_text(redacted.text, max_chars)
    return SanitizedText(
        capped.text,
        capped=capped.capped,
        redacted=redacted.redacted,
    )


def sanitize_line(text: str, *, max_chars: int = MAX_MATCH_LINE_CHARS) -> SanitizedText:
    """Sanitize one model-visible line or snippet."""

    return sanitize_text(text, max_chars=max_chars)


def sanitize_command_output(text: str) -> SanitizedText:
    """Sanitize stdout or stderr before returning it to a model."""

    return sanitize_text(text, max_chars=MAX_COMMAND_OUTPUT_CHARS)


def line_window(
    content: str | bytes,
    *,
    path: str | Path | None = None,
    start_line: int = 1,
    limit: int = DEFAULT_FILE_LINE_LIMIT,
) -> LineWindow:
    """Return a sanitized, capped line window from text file content."""

    text = decode_text_content(content, path=path)
    requested_limit = limit
    effective_limit = max(1, min(int(limit), MAX_FILE_LINE_LIMIT))
    effective_start = max(1, int(start_line))

    raw_lines = text.splitlines(keepends=True)
    total_lines = len(raw_lines)
    if total_lines == 0 or effective_start > total_lines:
        return LineWindow(
            content="",
            start_line=effective_start,
            end_line=total_lines,
            total_lines=total_lines,
            has_more=False,
            next_start_line=None,
            capped=False,
            redacted=False,
            requested_limit=requested_limit,
            effective_limit=effective_limit,
        )

    start_index = effective_start - 1
    selected = raw_lines[start_index : start_index + effective_limit]
    safe = redact_secret_lines("".join(selected))
    capped_content, end_line, char_capped = _cap_lines_with_end_line(
        safe.text.splitlines(keepends=True),
        first_line_number=effective_start,
        max_chars=MAX_FILE_CHARS,
    )

    window_end_line = end_line if selected else effective_start - 1
    line_capped = start_index + len(selected) < total_lines
    capped = line_capped or char_capped
    has_more = window_end_line < total_lines or char_capped
    next_start_line = window_end_line + 1 if has_more else None

    return LineWindow(
        content=capped_content,
        start_line=effective_start,
        end_line=window_end_line,
        total_lines=total_lines,
        has_more=has_more,
        next_start_line=next_start_line,
        capped=capped,
        redacted=safe.redacted,
        requested_limit=requested_limit,
        effective_limit=effective_limit,
    )


def sanitize_file_window(
    content: str | bytes,
    *,
    path: str | Path,
    start_line: int = 1,
    limit: int = DEFAULT_FILE_LINE_LIMIT,
) -> LineWindow:
    """Explicit file-read wrapper around :func:`line_window`."""

    return line_window(content, path=path, start_line=start_line, limit=limit)


def _cap_lines_with_end_line(
    lines: list[str],
    *,
    first_line_number: int,
    max_chars: int,
) -> tuple[str, int, bool]:
    consumed: list[str] = []
    remaining = max_chars
    end_line = first_line_number - 1
    capped = False

    for offset, line in enumerate(lines):
        line_number = first_line_number + offset
        if len(line) <= remaining:
            consumed.append(line)
            remaining -= len(line)
            end_line = line_number
            continue
        if remaining > 0:
            consumed.append(line[:remaining])
            end_line = line_number
        capped = True
        break

    return "".join(consumed), end_line, capped


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""
