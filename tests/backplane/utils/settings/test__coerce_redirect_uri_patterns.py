"""Tests for redirect URI pattern coercion used by MCP OAuth settings."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from backplane.utils.settings import _coerce_redirect_uri_patterns

if TYPE_CHECKING:
    from pytest_mock import MockerFixture


def test__coerce_redirect_uri_patterns__parses_comma_separated_string() -> None:
    """Comma-separated env values are split into individual patterns."""
    assert _coerce_redirect_uri_patterns(
        "https://chatgpt.com/connector/oauth/*, http://localhost:8787/callback",
    ) == [
        "https://chatgpt.com/connector/oauth/*",
        "http://localhost:8787/callback",
    ]


def test__coerce_redirect_uri_patterns__rejects_json_non_list(
    mocker: MockerFixture,
) -> None:
    """JSON-looking values that do not decode to a list are rejected."""
    _ = mocker.patch(
        "backplane.utils.settings.json.loads",
        return_value={"not": "a list"},
    )

    with pytest.raises(TypeError, match="JSON list of strings"):
        _ = _coerce_redirect_uri_patterns('["ignored"]')


def test__coerce_redirect_uri_patterns__rejects_non_string_list_items() -> None:
    """List/tuple items must be strings."""
    with pytest.raises(TypeError, match="must be a string"):
        _ = _coerce_redirect_uri_patterns(["https://ok.example/callback", 1])


def test__coerce_redirect_uri_patterns__rejects_unsupported_types() -> None:
    """Unsupported value types raise a TypeError."""
    with pytest.raises(TypeError, match="invalid redirect URI patterns"):
        _ = _coerce_redirect_uri_patterns(42)
