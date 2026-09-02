"""Authentication boundary for sensitive context REST operations."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backplane.utils import SETTINGS, exc

_BEARER = HTTPBearer(auto_error=False)


def require_context_api_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_BEARER)],
) -> None:
    """Require the dedicated context-ingestion bearer token.

    Raises:
        ServiceUnavailableError: If the context REST token is not configured.
        UnauthorizedError: If the caller does not provide the configured token.
    """
    configured = SETTINGS.context_api_token
    if configured is None or not (expected := configured.get_secret_value()):
        msg = "CONTEXT_API_TOKEN is required for context REST operations."
        raise exc.ServiceUnavailableError(message=msg)
    if (
        credentials is None
        or credentials.scheme.lower() != "bearer"
        or not secrets.compare_digest(credentials.credentials, expected)
    ):
        msg = "A valid context API bearer token is required."
        raise exc.UnauthorizedError(message=msg)
