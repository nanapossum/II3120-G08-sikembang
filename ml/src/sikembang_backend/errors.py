"""D2 error envelopes for the host application."""

import logging

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)

CODES = {
    400: "VALIDATION_ERROR", 401: "UNAUTHORIZED", 403: "FORBIDDEN_ROLE", 404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 422: "BUSINESS_RULE_VIOLATION", 500: "INTERNAL_ERROR",
}


class AppError(HTTPException):
    def __init__(self, status, code, message, details=None, headers=None):
        super().__init__(status, message, headers=headers)
        self.code = code
        self.details = details or {}


def install_handlers(app):
    def envelope(status, code, message, details=None, headers=None):
        return JSONResponse(
            {"error": {"code": code, "message": message, "details": details or {}}},
            status_code=status, headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        fields = [{"field": ".".join(map(str, item["loc"])), "reason": item["type"]}
                  for item in exc.errors()]
        return envelope(400, "VALIDATION_ERROR", "Bentuk permintaan tidak valid.", {"fields": fields})

    @app.exception_handler(HTTPException)
    async def http_failure(request, exc):
        code = getattr(exc, "code", CODES.get(exc.status_code, "HTTP_ERROR"))
        message = exc.detail if isinstance(exc.detail, str) else "Permintaan gagal."
        if exc.status_code >= 500 and not isinstance(exc, AppError):
            message = "Terjadi kegagalan internal."
        return envelope(exc.status_code, code, message, getattr(exc, "details", None), exc.headers)

    @app.exception_handler(Exception)
    async def unexpected_failure(request, exc):
        logger.error("Unexpected application failure", exc_info=exc)
        return envelope(500, "INTERNAL_ERROR", "Terjadi kegagalan internal.")
