# ruff:file-ignore[undocumented-public-init]
"""Exceptions for Backplane."""

from __future__ import annotations

from http import HTTPStatus
from typing import final

from pydantic_core import to_jsonable_python


class BackplaneError(Exception):
    """Base exception for Backplane."""

    def __init__(self, message: str, detail: object = None) -> None:
        self.message: str = message
        self.detail: object = to_jsonable_python(detail, fallback=str)

        super().__init__(self.message)


class InformationRequiredError(BackplaneError):
    """Raised when more information is needed to complete the action."""


class UserError(BackplaneError):
    """Raised due to incorrect usage of <something> by an actor (dev, user, agent, etc.)."""


# =============================================================================
# Base Status Code Errors

# These errors can be used directly or as a mixin to provide more context.


class BadRequestError(BackplaneError):
    """Generic error raised when a request is invalid."""

    STATUS_CODE: HTTPStatus = HTTPStatus.BAD_REQUEST


class UnauthorizedError(BackplaneError):
    """Generic error raised when a request is unauthorized."""

    STATUS_CODE: HTTPStatus = HTTPStatus.UNAUTHORIZED


class ForbiddenError(BackplaneError):
    """Generic error raised when a request is forbidden."""

    STATUS_CODE: HTTPStatus = HTTPStatus.FORBIDDEN


class NotFoundError(BackplaneError):
    """Generic error raised when a resource is not found."""

    STATUS_CODE: HTTPStatus = HTTPStatus.NOT_FOUND


class ConflictError(BackplaneError):
    """Generic error raised when a resource is in conflict with another resource."""

    STATUS_CODE: HTTPStatus = HTTPStatus.CONFLICT


class UnprocessableEntityError(BackplaneError):
    """Generic error raised when a request is unprocessable."""

    STATUS_CODE: HTTPStatus = HTTPStatus.UNPROCESSABLE_ENTITY


class TooManyRequestsError(BackplaneError):
    """Generic error raised when too many requests are made."""

    STATUS_CODE: HTTPStatus = HTTPStatus.TOO_MANY_REQUESTS


class InternalServerError(BackplaneError):
    """Generic error raised when an internal server error occurs."""

    STATUS_CODE: HTTPStatus = HTTPStatus.INTERNAL_SERVER_ERROR


class BadGatewayError(BackplaneError):
    """Generic error raised when a bad gateway occurs."""

    STATUS_CODE: HTTPStatus = HTTPStatus.BAD_GATEWAY


class ServiceUnavailableError(BackplaneError):
    """Generic error raised when a service is unavailable."""

    STATUS_CODE: HTTPStatus = HTTPStatus.SERVICE_UNAVAILABLE


@final
class SectionNotFoundError(NotFoundError):
    """Raised when a section is not found."""

    def __init__(
        self,
        section: str,
        parent: str | None = None,
        siblings: list[str] | None = None,
    ) -> None:
        self.section = section
        self.parent = parent
        self.siblings = siblings

        message = f"Section {section!r} not found"
        if parent is not None:
            message += f" under {parent!r}"
        message += "."
        if siblings is not None:
            message += f" Available sections: {', '.join(siblings)}."

        super().__init__(
            message,
            detail={"section": section, "parent": parent, "siblings": siblings},
        )
