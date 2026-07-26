"""OAuth authentication for the public Backplane MCP server.

Scope model (current):
    The public MCP server requires authentication globally. Core tools and
    resources use baseline scope ``openid``. Home Assistant upstream tools
    additionally require ``backplane.home-assistant`` so Authentik can grant
    HA access per OAuth application (for example ChatGPT only).

Future (deferred):
    A fuller MCP design may split read vs write tools using ``mcp.read`` and
    ``mcp.write``. Do not add that split until the live ChatGPT → FastMCP →
    Authentik flow is verified and we know which scopes are requested, issued,
    preserved, and visible to ``require_scopes`` during tool execution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal, NotRequired, TypedDict

from fastmcp.server.auth import require_scopes
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration, OIDCProxy
from fastmcp.server.auth.providers.introspection import IntrospectionTokenVerifier
from loguru import logger

from backplane.utils.exceptions import UserError
from backplane.utils.settings import SETTINGS

# Cache introspection briefly so every MCP tool call does not hit Authentik.
_INTROSPECTION_CACHE_TTL_SECONDS: Final = 60

if TYPE_CHECKING:
    from fastmcp.server.auth import AuthProvider
    from fastmcp.utilities.authorization import AuthCheck

MCP_BASELINE_SCOPE: Final = "openid"

# Extra scope for Home Assistant upstream tools on the public MCP server.
# Configure this scope on the Authentik Backplane MCP provider and grant it
# only to OAuth apps that should see HA tools (for example ChatGPT).
HA_MCP_SCOPE: Final = "backplane.home-assistant"

# Requested on /authorize so Authentik returns a refresh token upstream; FastMCP
# then includes refresh_token in /token responses (required for ChatGPT MCP).
# ``HA_MCP_SCOPE`` is advertised so clients that should get HA can request it;
# Authentik decides whether to issue it for a given application.
MCP_AUTHORIZE_SCOPES: Final[tuple[str, ...]] = (
    MCP_BASELINE_SCOPE,
    "offline_access",
    HA_MCP_SCOPE,
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

    auth_provider = OIDCProxy(
        config_url=oidc_config_url,
        client_id=client_id,
        client_secret=client_secret,
        base_url=public_base_url,
        require_authorization_consent="external",
        allowed_client_redirect_uris=SETTINGS.allowed_client_redirect_uri_patterns,
        token_verifier=token_verifier,
    )
    auth_provider.required_scopes = [MCP_BASELINE_SCOPE]
    auth_provider.update_default_scopes(list(MCP_AUTHORIZE_SCOPES))
    return auth_provider
