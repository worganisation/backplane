"""HTTP error handling for the Backplane REST API."""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from backplane.api.schemas import ErrorResponse
from backplane.utils import exc

if TYPE_CHECKING:
    from fastapi import Request


def _backplane_error_status(error: exc.BackplaneError) -> int:
    """Return the HTTP status code for a Backplane domain error."""
    if isinstance(error, exc.InformationRequiredError):
        return HTTPStatus.UNPROCESSABLE_ENTITY
    if isinstance(error, exc.UserError):
        return HTTPStatus.BAD_REQUEST
    return int(getattr(error, "STATUS_CODE", HTTPStatus.BAD_REQUEST))


def handle_backplane_error(_request: Request, error: Exception) -> JSONResponse:
    """Serialize a Backplane domain error into the REST error envelope.

    Returns:
        JSON error response.

    Raises:
        TypeError: If FastAPI invokes the handler for a non-Backplane exception.
    """
    if isinstance(error, exc.BackplaneError):
        return JSONResponse(
            status_code=_backplane_error_status(error),
            content=ErrorResponse(message=error.message, detail=error.detail).model_dump(
                mode="json",
            ),
        )
    raise TypeError(error)
