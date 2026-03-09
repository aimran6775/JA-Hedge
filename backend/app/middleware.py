"""
JA Hedge — Custom Middleware.

- Request ID tracking
- Request timing / latency logging
- Global error handling
"""

from __future__ import annotations

import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging_config import get_logger

log = get_logger("middleware")


class RequestTrackingMiddleware(BaseHTTPMiddleware):
    """Attach a unique request ID and log timing for every request."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())[:12]
        start = time.monotonic()

        # Attach to request state for downstream use
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            log.error(
                "request_error",
                method=request.method,
                path=request.url.path,
                request_id=request_id,
                error=str(exc),
                latency_ms=round(elapsed, 2),
            )
            raise

        elapsed = (time.monotonic() - start) * 1000
        response.headers["x-request-id"] = request_id
        response.headers["x-response-time"] = f"{elapsed:.1f}ms"

        if elapsed > 2000:
            log.warning(
                "slow_request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                latency_ms=round(elapsed, 2),
                request_id=request_id,
            )
        else:
            log.info(
                "request",
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                latency_ms=round(elapsed, 2),
                request_id=request_id,
            )

        return response
