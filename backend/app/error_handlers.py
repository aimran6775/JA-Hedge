"""
JA Hedge — Global Exception Handlers.

Converts all known and unknown exceptions into structured JSON responses
so the frontend always gets a consistent error shape.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.kalshi.exceptions import (
    KalshiError,
    KalshiAuthError,
    KalshiRateLimitError,
    KalshiOrderError,
    KalshiNotFoundError,
    KalshiValidationError,
    KalshiServerError,
    KalshiConnectionError,
)
from app.logging_config import get_logger

log = get_logger("errors")


def register_exception_handlers(app: FastAPI) -> None:
    """Attach all exception handlers to the FastAPI app."""

    @app.exception_handler(KalshiAuthError)
    async def auth_error(request: Request, exc: KalshiAuthError) -> JSONResponse:
        log.warning("auth_error", path=request.url.path, detail=str(exc))
        return JSONResponse(
            status_code=401,
            content={"error": "authentication_failed", "detail": str(exc)},
        )

    @app.exception_handler(KalshiRateLimitError)
    async def rate_limit_error(request: Request, exc: KalshiRateLimitError) -> JSONResponse:
        log.warning("rate_limited", path=request.url.path)
        return JSONResponse(
            status_code=429,
            content={"error": "rate_limited", "detail": str(exc), "retry_after": 1},
        )

    @app.exception_handler(KalshiNotFoundError)
    async def not_found_error(request: Request, exc: KalshiNotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found", "detail": str(exc)},
        )

    @app.exception_handler(KalshiValidationError)
    async def validation_error(request: Request, exc: KalshiValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"error": "validation_error", "detail": str(exc)},
        )

    @app.exception_handler(KalshiOrderError)
    async def order_error(request: Request, exc: KalshiOrderError) -> JSONResponse:
        log.error("order_error", path=request.url.path, detail=str(exc))
        return JSONResponse(
            status_code=400,
            content={"error": "order_error", "detail": str(exc)},
        )

    @app.exception_handler(KalshiServerError)
    async def server_error(request: Request, exc: KalshiServerError) -> JSONResponse:
        log.error("kalshi_server_error", detail=str(exc))
        return JSONResponse(
            status_code=502,
            content={"error": "upstream_error", "detail": "Kalshi API returned a server error"},
        )

    @app.exception_handler(KalshiConnectionError)
    async def connection_error(request: Request, exc: KalshiConnectionError) -> JSONResponse:
        log.error("kalshi_connection_error", detail=str(exc))
        return JSONResponse(
            status_code=503,
            content={"error": "connection_error", "detail": "Cannot reach Kalshi API"},
        )

    @app.exception_handler(KalshiError)
    async def generic_kalshi_error(request: Request, exc: KalshiError) -> JSONResponse:
        log.error("kalshi_error", detail=str(exc))
        return JSONResponse(
            status_code=500,
            content={"error": "kalshi_error", "detail": str(exc)},
        )

    @app.exception_handler(Exception)
    async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        log.critical(
            "unhandled_exception",
            path=request.url.path,
            error_type=type(exc).__name__,
            detail=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "detail": "An unexpected error occurred"},
        )
