"""Application settings for Backplane."""

from __future__ import annotations

import json
import zoneinfo
from typing import Annotated, ClassVar, Final, Self, cast, final

import yarl
from pydantic import (
    AnyHttpUrl,
    BeforeValidator,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from .async_path import AsyncPath
from .exceptions import UserError


def _parse_timezone(v: object) -> zoneinfo.ZoneInfo:
    if isinstance(v, zoneinfo.ZoneInfo):
        return v
    try:
        return zoneinfo.ZoneInfo(str(v))
    except zoneinfo.ZoneInfoNotFoundError as exc:
        msg = f"invalid timezone {v!r}: provide a valid IANA timezone name, e.g. 'Europe/London'"
        raise ValueError(msg) from exc


def _coerce_redirect_uri_patterns(v: object) -> list[str]:
    if not v:
        return []

    if isinstance(v, str):
        stripped = v.strip()
        if stripped.startswith("["):
            parsed_unknown = json.loads(stripped)  # pyright: ignore[reportAny]
            if not isinstance(parsed_unknown, list):
                msg = "redirect URI patterns must be a JSON list of strings"
                raise TypeError(msg)
            return _coerce_redirect_uri_patterns(cast("list[object]", parsed_unknown))
        return [part.strip() for part in stripped.split(",") if part.strip()]

    if isinstance(v, (list, tuple)):
        patterns: list[str] = []
        for item in cast("list[object] | tuple[object, ...]", v):
            if not isinstance(item, str):
                msg = f"redirect URI pattern must be a string, got {item!r}"
                raise TypeError(msg)
            patterns.append(item)
        return patterns

    msg = f"invalid redirect URI patterns: {v!r}"
    raise TypeError(msg)


_MCP_OAUTH_REQUIRED_MSG = (
    "Public MCP requires OAuth. Set MCP_PUBLIC_BASE_URL, "
    "MCP_OIDC_CONFIG_URL, MCP_OIDC_CLIENT_ID, and MCP_OIDC_CLIENT_SECRET."
)


class Settings(BaseSettings):
    """Settings for the Backplane application."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        case_sensitive=False,
        populate_by_name=True,
    )

    local_timezone: Annotated[
        zoneinfo.ZoneInfo,
        BeforeValidator(_parse_timezone),
        Field(
            description=(
                "IANA timezone used for date/timestamp calculations, e.g. 'Europe/London'. "
                "Overridable via the LOCAL_TIMEZONE environment variable."
            ),
        ),
    ] = zoneinfo.ZoneInfo("Europe/London")

    # ========================================================================
    # Canonical context capture

    context_database_url: Annotated[
        SecretStr | None,
        Field(
            description=(
                "SQLAlchemy async database URL for the context ledger, e.g. "
                "postgresql+asyncpg://user:password@postgres/backplane."
            ),
        ),
    ] = None

    context_api_token: Annotated[
        SecretStr | None,
        Field(
            description=(
                "Bearer token required by every sensitive context REST endpoint."
            ),
        ),
    ] = None

    context_database_echo: Annotated[
        bool,
        Field(description="Whether to log SQL emitted by the context persistence layer."),
    ] = False

    # ========================================================================
    # Home Assistant

    home_assistant_url: Annotated[
        yarl.URL | None,
        Field(
            description="Base URL of the Home Assistant instance, e.g. http://homeassistant.local:8123.",
        ),
    ] = None

    home_assistant_token: Annotated[
        str | None,
        Field(
            description="Long-lived access token for the Home Assistant REST API.",
        ),
    ] = None

    home_assistant_mcp_entry_id: Annotated[
        str | None,
        Field(
            description="Config entry ID of the Backplane MCP integration in Home Assistant.",
        ),
    ] = None

    ha_mcp_enabled: Annotated[
        bool,
        Field(
            description="Whether to proxy the Home Assistant MCP add-on through Backplane.",
        ),
    ] = False

    ha_mcp_url: Annotated[
        str | None,
        Field(
            description=(
                "Private LAN URL of the Home Assistant MCP add-on, "
                "e.g. http://10.0.0.x:9583/<secret-path>."
            ),
        ),
    ] = None

    ha_mcp_namespace: Annotated[
        str,
        Field(description="Namespace prefix for mounted HA MCP tools."),
    ] = "ha"

    ha_mcp_client_redirect_uri_patterns: Annotated[
        tuple[str, ...],
        BeforeValidator(_coerce_redirect_uri_patterns),
        Field(
            description=(
                "Redirect URI patterns identifying downstream OAuth clients "
                "allowed to receive the Home Assistant MCP scope. Defaults to "
                "MCP_CLIENT_REDIRECT_URI_PATTERNS when unset."
            ),
        ),
        NoDecode,
    ] = ()

    @model_validator(mode="after")
    def _inherit_ha_mcp_redirect_uri_patterns(self) -> Self:
        """Reuse the shared DCR allowlist for HA scope gating when HA list is unset.

        Returns:
            Settings with HA redirect patterns inherited when needed.
        """
        if (
            self.ha_mcp_client_redirect_uri_patterns
            or not self.allowed_client_redirect_uri_patterns
        ):
            return self
        # BaseSettings `__init__` ignores model_validator return values other
        # than `self`, so mutate in place rather than `model_copy`.
        self.ha_mcp_client_redirect_uri_patterns = tuple(
            self.allowed_client_redirect_uri_patterns,
        )
        return self

    @field_validator("home_assistant_url", mode="before")
    @classmethod
    def _parse_ha_url(cls, v: yarl.URL | str | None) -> yarl.URL | None:
        if v is None:
            return None
        if isinstance(v, yarl.URL):
            return v
        return yarl.URL(v.rstrip("/"))

    # ========================================================================
    # LLM

    task_metadata_model: Annotated[
        str,
        Field(
            description=(
                "PydanticAI model string used for task metadata extraction, "
                "e.g. 'anthropic:claude-haiku-4-5-20251001' or 'openai:gpt-4o-mini'."
            ),
        ),
    ] = "openai:gpt-4o-mini"

    # ========================================================================
    # Obsidian

    obsidian_vault_path: Annotated[
        AsyncPath,
        Field(description="Absolute path to the Obsidian vault directory."),
    ]

    @field_validator("obsidian_vault_path", mode="before")
    @classmethod
    def _parse_obsidian_vault_path(cls, v: AsyncPath | str) -> AsyncPath:
        """Coerce a value to an AsyncPath.

        Returns:
                AsyncPath: The value as an AsyncPath.
        """
        if isinstance(v, AsyncPath):
            return v
        return AsyncPath(v)

    # ========================================================================
    # Public MCP OAuth (Authentik via FastMCP OIDCProxy)

    mcp_public_base_url: Annotated[
        AnyHttpUrl | None,
        Field(
            description=(
                "Public HTTPS base URL of the ChatGPT-facing MCP server, "
                "e.g. https://backplane-mcp.example.com."
            ),
        ),
    ] = None

    mcp_oidc_config_url: Annotated[
        AnyHttpUrl | None,
        Field(
            description=(
                "Authentik OIDC discovery URL for the Backplane MCP application, "
                "e.g. https://auth.example.com/application/o/backplane-mcp/"
                ".well-known/openid-configuration."
            ),
        ),
    ] = None

    mcp_oidc_client_id: Annotated[
        str | None,
        Field(
            description="OAuth client ID from the Authentik Backplane MCP provider.",
        ),
    ] = None

    mcp_oidc_client_secret: Annotated[
        str | None,
        Field(
            description="OAuth client secret from the Authentik Backplane MCP provider.",
        ),
    ] = None

    allowed_client_redirect_uri_patterns: Annotated[
        list[str],
        BeforeValidator(_coerce_redirect_uri_patterns),
        NoDecode,
    ] = Field(
        default_factory=list,
        validation_alias="MCP_CLIENT_REDIRECT_URI_PATTERNS",
        description=("Redirect URI patterns permitted for downstream MCP OAuth clients."),
    )

    @property
    def mcp_oauth_configured(self) -> bool:
        """Whether the public MCP OAuth settings are complete."""
        return (
            self.mcp_public_base_url is not None
            and self.mcp_oidc_config_url is not None
            and self.mcp_oidc_client_id is not None
            and self.mcp_oidc_client_secret is not None
        )

    def require_mcp_oauth(self) -> tuple[AnyHttpUrl, AnyHttpUrl, str, str]:
        """Return validated public MCP OAuth settings.

        Returns:
            Public base URL, OIDC discovery URL, client ID, and client secret.

        Raises:
            UserError: If any required OAuth setting is missing.
        """
        public_base_url = self.mcp_public_base_url
        oidc_config_url = self.mcp_oidc_config_url
        client_id = self.mcp_oidc_client_id
        client_secret = self.mcp_oidc_client_secret
        if (
            public_base_url is None
            or oidc_config_url is None
            or client_id is None
            or client_secret is None
        ):
            raise UserError(
                message=_MCP_OAUTH_REQUIRED_MSG,
                detail={
                    "public_base_url": public_base_url,
                    "oidc_config_url": oidc_config_url,
                    "client_id": client_id,
                    "client_secret": (
                        (client_secret[:8] + "..." + client_secret[-8:])
                        if client_secret
                        else None
                    ),
                },
            )

        return public_base_url, oidc_config_url, client_id, client_secret

    def require_ha_mcp_url(self) -> str:
        """Return the HA MCP add-on URL when upstream proxying is enabled.

        Returns:
            Private LAN URL of the Home Assistant MCP add-on.

        Raises:
            UserError: If HA MCP is enabled but the URL is missing.
        """
        url = self.ha_mcp_url
        if not self.ha_mcp_enabled:
            msg = "HA MCP upstream is disabled."
            raise UserError(message=msg)
        if url is None or not url.strip():
            msg = "HA_MCP_URL is required when HA_MCP_ENABLED is true."
            raise UserError(message=msg)
        return url.strip()


@final
class VaultPaths:
    """Stable relative paths within the Obsidian vault."""

    daily_notes_dir: Final = AsyncPath("Daily Notes")

    domains_dir: Final = AsyncPath("Domains")

    inbox_dir: Final = AsyncPath("Inbox")

    people_dir: Final = AsyncPath("People")

    projects_dir: Final = AsyncPath("Projects")
    project_board_path: Final = projects_dir / "Projects Board.md"

    resources_dir: Final = AsyncPath("Resources")

    templates_dir: Final = AsyncPath("Templates")

    tasks_dir: Final = AsyncPath("Tasks")
    task_notes_dir: Final = tasks_dir / "Tasks"
    task_board_path: Final = tasks_dir / "Tasks Board.md"


SETTINGS: Final = Settings()  # pyright: ignore[reportCallIssue]
VAULT_PATHS: Final = VaultPaths()


__all__ = ["SETTINGS", "VAULT_PATHS", "VaultPaths"]
