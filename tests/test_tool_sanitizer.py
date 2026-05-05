from __future__ import annotations

import pytest

from specode.tool_sanitizer import (
    DEFAULT_FILE_LINE_LIMIT,
    MAX_FILE_CHARS,
    MAX_FILE_LINE_LIMIT,
    MAX_MATCH_LINE_CHARS,
    BinaryContentError,
    SecretFileError,
    contains_secret_marker,
    is_secret_file_path,
    line_window,
    sanitize_file_window,
    sanitize_line,
)


def test_secret_env_files_are_blocked_except_examples() -> None:
    assert is_secret_file_path(".env")
    assert is_secret_file_path(".env.local")
    assert is_secret_file_path("deploy/prod.env.secret")
    assert not is_secret_file_path(".env.example")
    assert not is_secret_file_path("service.env")


def test_secret_file_window_blocks_before_returning_content() -> None:
    with pytest.raises(SecretFileError):
        sanitize_file_window("OPENAI_API_KEY=secret\n", path=".env.local")


def test_binary_content_is_refused_before_decoding() -> None:
    with pytest.raises(BinaryContentError):
        line_window(b"\x89PNG\x00payload", path="image.bin")


def test_line_window_defaults_to_200_lines_and_reports_pagination() -> None:
    content = "".join(f"{line}\n" for line in range(250))

    window = line_window(content)

    assert window.start_line == 1
    assert window.end_line == DEFAULT_FILE_LINE_LIMIT
    assert window.total_lines == 250
    assert window.has_more
    assert window.next_start_line == 201
    assert window.capped
    assert len(window.content.splitlines()) == DEFAULT_FILE_LINE_LIMIT


def test_line_window_clamps_limit_to_maximum() -> None:
    content = "".join(f"{line}\n" for line in range(MAX_FILE_LINE_LIMIT + 10))

    window = line_window(content, limit=MAX_FILE_LINE_LIMIT + 10)

    assert window.effective_limit == MAX_FILE_LINE_LIMIT
    assert window.end_line == MAX_FILE_LINE_LIMIT
    assert window.has_more
    assert window.next_start_line == MAX_FILE_LINE_LIMIT + 1


def test_line_window_supports_repeated_range_reads() -> None:
    content = "one\ntwo\nthree\nfour\n"

    first = line_window(content, start_line=2, limit=2)
    second = line_window(content, start_line=first.next_start_line or 1, limit=2)

    assert first.content == "two\nthree\n"
    assert first.next_start_line == 4
    assert second.content == "four\n"
    assert not second.has_more


def test_line_window_redacts_secret_like_lines() -> None:
    content = "safe\napi_key = 'secret'\npassword: nope\nsafe again\n"

    window = line_window(content, limit=10)

    assert "secret" not in window.content
    assert "nope" not in window.content
    assert "[REDACTED]" in window.content
    assert window.redacted
    assert contains_secret_marker("private_key = value")


def test_line_window_enforces_hard_character_backstop() -> None:
    content = "a" * (MAX_FILE_CHARS + 25) + "\nsecond\n"

    window = line_window(content, limit=10)

    assert len(window.content) == MAX_FILE_CHARS
    assert window.capped
    assert window.has_more


def test_sanitize_line_caps_and_redacts_search_matches() -> None:
    secret = sanitize_line("token=abc123", max_chars=MAX_MATCH_LINE_CHARS)
    long_line = sanitize_line("x" * (MAX_MATCH_LINE_CHARS + 1))

    assert secret.text == "[REDACTED]"
    assert secret.redacted
    assert len(long_line.text) == MAX_MATCH_LINE_CHARS
    assert long_line.capped
