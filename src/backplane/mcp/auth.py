"""OAuth authentication for the public Backplane MCP server.

Scope model (current):
    The public MCP server requires authentication globally. Core tools and
    resources use baseline scope ``openid``. Home Assistant upstream components
    additionally require ``backplane.home-assistant``. Backplane restricts that
    optional scope by downstream client's registered redirect URIs.

Future (deferred):
    A fuller MCP design may split read vs write tools using ``mcp.read`` and
    ``mcp.write``. Do not add that split until the live ChatGPT → FastMCP →
    Authentik flow is verified and we know which scopes are requested, issued,
    preserved, and visible to ``require_scopes`` during tool execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal, NotRequired, TypedDict, override

from fastmcp.server.auth import require_scopes
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration, OIDCProxy
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier
from fastmcp.server.auth.redirect_validation import matches_allowed_pattern
from loguru import logger

from backplane.mcp.upstreams.registry import HA_MCP_SCOPE, get_enabled_upstreams
from backplane.utils.exceptions import UserError
from backplane.utils.settings import SETTINGS, Settings

__all__ = [
    "HA_MCP_SCOPE",
    "MCP_AUTHORIZE_SCOPES",
    "MCP_BASELINE_SCOPE",
    "OAuthToolRegistrationKwargs",
    "ScopedClientOIDCProxy",
    "create_public_mcp_auth",
    "mcp_authorize_scopes",
    "oauth_tool_meta",
    "oauth_tool_registration_kwargs",
]

# Cache introspection briefly so every MCP tool call does not hit Authentik.
_INTROSPECTION_CACHE_TTL_SECONDS: Final = 60

if TYPE_CHECKING:
    from fastmcp.server.auth import AuthProvider
    from fastmcp.utilities.authorization import AuthCheck
    from mcp.shared.auth import OAuthClientInformationFull

MCP_BASELINE_SCOPE: Final = "openid"

# Requested on /authorize so Authentik returns a refresh token upstream; FastMCP
# then includes refresh_token in /token responses (required for ChatGPT MCP).
MCP_AUTHORIZE_SCOPES: Final[tuple[str, ...]] = (
    MCP_BASELINE_SCOPE,
    "offline_access",
)


class OAuthSecurityScheme(TypedDict):
    """OAuth2 security scheme advertised to ChatGPT MCP clients."""

    type: Literal["oauth2"]
    scopes: list[str]


class OAuthToolMeta(TypedDict):
    """MCP tool metadata that advertises OAuth requirements."""

    securitySchemes: list[OAuthSecurityScheme]


class OAuthToolRegistrationKwargs(TypedDict):
    """FastMCP tool/resource registration kwargs for OAuth-protected components."""

    auth: NotRequired[AuthCheck]
    meta: NotRequired[dict[str, list[OAuthSecurityScheme]]]


class ScopedClientOIDCProxy(OIDCProxy):
    """Restrict optional scopes according to downstream client redirect URIs."""

    _direct_client_id: str
    _scope_redirect_uri_patterns: dict[str, tuple[str, ...]]

    def configure_client_scope_policy(
        self,
        *,
        direct_client_id: str,
        scope_redirect_uri_patterns: dict[str, tuple[str, ...]],
    ) -> None:
        """Configure downstream client scope entitlements."""
        self._direct_client_id = direct_client_id
        self._scope_redirect_uri_patterns = scope_redirect_uri_patterns

    def _allowed_scopes(
        self,
        client_info: OAuthClientInformationFull,
    ) -> tuple[str, ...]:
        redirect_uris = tuple(str(uri) for uri in client_info.redirect_uris or ())
        allowed_scopes: list[str] = list(MCP_AUTHORIZE_SCOPES)
        for scope, patterns in self._scope_redirect_uri_patterns.items():
            if redirect_uris and all(
                any(matches_allowed_pattern(uri, pattern) for pattern in patterns)
                for uri in redirect_uris
            ):
                allowed_scopes.append(scope)
        return tuple(allowed_scopes)

    @override
    async def register_client(
        self,
        client_info: OAuthClientInformationFull,
    ) -> None:
        """Register a downstream client with only its entitled scopes."""
        allowed_scopes = self._allowed_scopes(client_info)
        requested_scope = client_info.scope
        requested_scopes = set((requested_scope or " ".join(allowed_scopes)).split())
        client_info.scope = " ".join(
            scope for scope in allowed_scopes if scope in requested_scopes
        )
        logger.info(
            (
                "Registering downstream OAuth client with redirect URIs {}: "
                "requested scopes={!r}, allowed scopes={}, granted scopes={!r}"
            ),
            tuple(str(uri) for uri in client_info.redirect_uris or ()),
            requested_scope,
            allowed_scopes,
            client_info.scope,
        )
        await super().register_client(client_info)

    @override
    async def get_client(
        self,
        client_id: str,
    ) -> OAuthClientInformationFull | None:
        """Return a client, limiting direct non-DCR clients to baseline scopes."""
        client = await super().get_client(client_id)
        if client is not None and client_id == self._direct_client_id:
            client.scope = " ".join(MCP_AUTHORIZE_SCOPES)
        return client


def mcp_authorize_scopes(settings: Settings) -> tuple[str, ...]:
    """Return baseline and enabled-upstream scopes advertised to OAuth clients."""
    upstream_scopes = tuple(
        config.required_scope
        for config in get_enabled_upstreams(settings)
        if config.required_scope is not None
    )
    return (*MCP_AUTHORIZE_SCOPES, *upstream_scopes)


def oauth_tool_meta(*scopes: str) -> OAuthToolMeta:
    """Return MCP tool metadata that advertises OAuth to ChatGPT.

    Args:
        scopes: OAuth scopes to advertise. Defaults to ``MCP_BASELINE_SCOPE``.
    """
    effective_scopes = list(scopes) if scopes else [MCP_BASELINE_SCOPE]
    return {
        "securitySchemes": [{"type": "oauth2", "scopes": effective_scopes}],
    }


def oauth_tool_registration_kwargs(
    *scopes: str,
) -> OAuthToolRegistrationKwargs:
    """Return FastMCP registration kwargs for OAuth-protected tools and resources.

    Args:
        scopes: Required OAuth scopes for the component. Defaults to
            ``MCP_BASELINE_SCOPE`` when omitted.
    """
    effective_scopes = scopes or (MCP_BASELINE_SCOPE,)
    tool_meta = oauth_tool_meta(*effective_scopes)
    return {
        "auth": require_scopes(*effective_scopes),
        "meta": {"securitySchemes": tool_meta["securitySchemes"]},
    }


def create_public_mcp_auth() -> AuthProvider:
    """Build the OIDCProxy auth provider for the public MCP server.

    Returns:
        Configured auth provider for the public MCP server.

    Raises:
        UserError: When OAuth settings are incomplete or Authentik discovery
            omits a token introspection endpoint.
    """
    (
        public_base_url,
        oidc_config_url,
        client_id,
        client_secret,
    ) = SETTINGS.require_mcp_oauth()

    oidc_config = OIDCConfiguration.get_oidc_configuration(
        oidc_config_url,
        strict=None,
        timeout_seconds=None,
    )
    if not oidc_config.introspection_endpoint:
        msg = (
            "Authentik OIDC provider must expose an introspection endpoint. "
            f"None found in {oidc_config_url}"
        )
        raise UserError(msg)

    logger.info(
        "Configuring public MCP OAuth via Authentik OIDC proxy at {}",
        public_base_url,
    )

    token_verifier = IntrospectionTokenVerifier(
        introspection_url=str(oidc_config.introspection_endpoint),
        client_id=client_id,
        client_secret=client_secret,
        client_auth_method="client_secret_post",
        required_scopes=[MCP_BASELINE_SCOPE],
        cache_ttl_seconds=_INTROSPECTION_CACHE_TTL_SECONDS,
    )

    auth_provider = ScopedClientOIDCProxy(
        config_url=oidc_config_url,
        client_id=client_id,
        client_secret=client_secret,
        base_url=public_base_url,
        require_authorization_consent="external",
        allowed_client_redirect_uris=(
            SETTINGS.allowed_client_redirect_uri_patterns or None
        ),
        token_verifier=token_verifier,
    )
    auth_provider.configure_client_scope_policy(
        direct_client_id=client_id,
        scope_redirect_uri_patterns={
            config.required_scope: config.allowed_client_redirect_uri_patterns
            for config in get_enabled_upstreams(SETTINGS)
            if config.required_scope is not None
        },
    )
    auth_provider.required_scopes = [MCP_BASELINE_SCOPE]
    auth_provider.update_default_scopes(list(mcp_authorize_scopes(SETTINGS)))
    return auth_provider
