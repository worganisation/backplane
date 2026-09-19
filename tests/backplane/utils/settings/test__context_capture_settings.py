"""Tests for sensitive context-capture settings."""

from __future__ import annotations

from backplane.utils.settings import Settings


def test__context_settings__redact_database_credentials_and_api_token() -> None:
    """Settings representations never reveal context credentials."""
    database_credential = "database-credential-do-not-log"
    api_credential = "context-credential-do-not-log"
    settings = Settings.model_validate(
        {
            "obsidian_vault_path": "/tmp/vault",
            "context_database_url": (
                f"postgresql+asyncpg://backplane:{database_credential}@db/backplane"
            ),
            "context_api_token": api_credential,
        },
    )

    rendered = repr(settings)

    assert database_credential not in rendered
    assert api_credential not in rendered
    assert "**********" in rendered
