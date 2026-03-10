"""
JA Hedge — Kalshi Async REST Client.

High-performance HTTP client with:
- Persistent connection pool (HTTP/2)
- Auto-signing middleware
- Rate limiting
- Retry with exponential backoff
- Response parsing into Pydantic models
"""

from __future__ import annotations

import asyncio
from typing import Any, TypeVar

import httpx
import orjson

from app.kalshi.auth import KalshiAuth, NoAuth
from app.kalshi.exceptions import (
    KalshiConnectionError,
    KalshiError,
    KalshiServerError,
    STATUS_CODE_MAP,
)
from app.kalshi.rate_limiter import RateLimiter
from app.logging_config import get_logger

log = get_logger("kalshi.client")

T = TypeVar("T")

# HTTP methods that count as "write" for rate limiting
WRITE_METHODS = {"POST", "PUT", "DELETE", "PATCH"}


class KalshiClient:
    """
    Async Kalshi REST API client.

    Usage:
        async with KalshiClient(base_url=..., auth=auth) as client:
            markets = await client.get("/markets", params={"limit": 100})
            order = await client.post("/portfolio/orders", json=order_data)
    """

    def __init__(
        self,
        base_url: str,
        auth: KalshiAuth | NoAuth | None = None,
        rate_limiter: RateLimiter | None = None,
        max_retries: int = 3,
        timeout: float = 10.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._auth = auth or NoAuth()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._max_retries = max_retries
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> KalshiClient:
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(self._timeout, connect=5.0),
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30.0,
            ),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        log.info("kalshi_client_connected", base_url=self._base_url)
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            log.info("kalshi_client_closed")

    @property
    def is_connected(self) -> bool:
        return self._client is not None and not self._client.is_closed

    # ── Core Request Method ───────────────────────────────────────────────────

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> dict[str, Any]:
        """
        Make an authenticated request to the Kalshi API.

        Args:
            method: HTTP method
            path: API path (e.g., "/markets" — base URL is prepended)
            params: Query parameters
            json: Request body (will be serialized with orjson)
            authenticated: Whether to sign the request

        Returns:
            Parsed JSON response as dict

        Raises:
            KalshiError subclass on failure
        """
        if not self._client:
            raise KalshiConnectionError("Client not initialized. Use async with.")

        # Full path for signing
        full_path = f"/trade-api/v2{path}" if not path.startswith("/trade-api") else path

        # Rate limit
        if method.upper() in WRITE_METHODS:
            await self._rate_limiter.acquire_write()
        else:
            await self._rate_limiter.acquire_read()

        # Retry loop
        last_error: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                # Build headers
                headers: dict[str, str] = {}
                if authenticated:
                    headers = self._auth.sign(method.upper(), full_path)

                # Serialize body with orjson for speed
                content: bytes | None = None
                if json is not None:
                    content = orjson.dumps(json)
                    headers["Content-Type"] = "application/json"

                # Execute request
                response = await self._client.request(
                    method=method.upper(),
                    url=path,
                    params=params,
                    content=content,
                    headers=headers,
                )

                # Handle response
                if response.status_code == 204:
                    return {}

                body = orjson.loads(response.content) if response.content else {}

                if response.is_success:
                    return body

                # Error handling
                error_obj = body.get("error", {})
                if isinstance(error_obj, dict):
                    error_msg = error_obj.get("message", error_obj.get("code", str(error_obj)))
                else:
                    error_msg = body.get("message", str(error_obj or body))
                exc_class = STATUS_CODE_MAP.get(response.status_code, KalshiError)

                # Don't retry client errors (except 429)
                if response.status_code == 429:
                    retry_after = float(response.headers.get("Retry-After", 1.0))
                    log.warning(
                        "rate_limited",
                        attempt=attempt + 1,
                        retry_after=retry_after,
                    )
                    await asyncio.sleep(retry_after)
                    continue

                if 400 <= response.status_code < 500:
                    raise exc_class(
                        message=error_msg,
                        status_code=response.status_code,
                        body=body,
                    )

                # Server errors — retry
                if response.status_code >= 500:
                    last_error = KalshiServerError(
                        message=error_msg,
                        status_code=response.status_code,
                        body=body,
                    )
                    backoff = min(2**attempt * 0.5, 10.0)
                    log.warning(
                        "server_error_retry",
                        status=response.status_code,
                        attempt=attempt + 1,
                        backoff=backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

            except httpx.TimeoutException as e:
                last_error = KalshiConnectionError(f"Request timeout: {e}")
                backoff = min(2**attempt * 0.5, 10.0)
                log.warning("timeout_retry", attempt=attempt + 1, backoff=backoff)
                await asyncio.sleep(backoff)
                continue

            except httpx.ConnectError as e:
                last_error = KalshiConnectionError(f"Connection failed: {e}")
                backoff = min(2**attempt * 1.0, 15.0)
                log.warning("connection_error_retry", attempt=attempt + 1, backoff=backoff)
                await asyncio.sleep(backoff)
                continue

        # All retries exhausted
        raise last_error or KalshiError("Request failed after all retries")

    # ── Convenience Methods ───────────────────────────────────────────────────

    async def get(
        self, path: str, *, params: dict[str, Any] | None = None, authenticated: bool = True
    ) -> dict[str, Any]:
        return await self.request("GET", path, params=params, authenticated=authenticated)

    async def post(
        self, path: str, *, json: dict[str, Any] | None = None, authenticated: bool = True
    ) -> dict[str, Any]:
        return await self.request("POST", path, json=json, authenticated=authenticated)

    async def put(
        self, path: str, *, json: dict[str, Any] | None = None, authenticated: bool = True
    ) -> dict[str, Any]:
        return await self.request("PUT", path, json=json, authenticated=authenticated)

    async def delete(
        self, path: str, *, params: dict[str, Any] | None = None, authenticated: bool = True
    ) -> dict[str, Any]:
        return await self.request("DELETE", path, params=params, authenticated=authenticated)

    # ── Paginated Fetching ────────────────────────────────────────────────────

    async def get_all_pages(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        data_key: str = "markets",
        limit: int = 200,
        max_pages: int = 50,
        authenticated: bool = True,
    ) -> list[dict[str, Any]]:
        """
        Fetch all pages of a paginated endpoint.

        Args:
            path: API path
            params: Base query params
            data_key: Key in response containing the data list
            limit: Items per page
            max_pages: Safety limit on total pages
            authenticated: Whether to sign

        Returns:
            Combined list of all items across pages
        """
        all_items: list[dict[str, Any]] = []
        cursor: str | None = None
        page_params = dict(params or {})
        page_params["limit"] = limit

        for page_num in range(max_pages):
            if cursor:
                page_params["cursor"] = cursor

            response = await self.get(path, params=page_params, authenticated=authenticated)
            items = response.get(data_key, [])
            all_items.extend(items)

            cursor = response.get("cursor")
            if not cursor or not items:
                break

            log.debug("pagination", page=page_num + 1, items_so_far=len(all_items))

        return all_items
