"""
JA Hedge — Token Bucket Rate Limiter.

Enforces Kalshi rate limits locally to avoid 429 errors.
Separate buckets for read and write operations.
"""

from __future__ import annotations

import asyncio
import time

from app.logging_config import get_logger

log = get_logger("kalshi.rate_limiter")


class TokenBucket:
    """
    Async token bucket rate limiter.

    Refills tokens at a constant rate.
    acquire() blocks until a token is available.
    """

    def __init__(self, rate: float, capacity: float | None = None):
        """
        Args:
            rate: Tokens per second
            capacity: Max burst capacity (defaults to rate)
        """
        self._rate = rate
        self._capacity = capacity or rate
        self._tokens = self._capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: float = 1.0) -> float:
        """
        Acquire tokens, waiting if necessary.

        Returns: wait time in seconds (0.0 if no wait needed)
        """
        async with self._lock:
            self._refill()

            if self._tokens >= tokens:
                self._tokens -= tokens
                return 0.0

            # Calculate wait time
            deficit = tokens - self._tokens
            wait_time = deficit / self._rate

            # Wait and then consume
            await asyncio.sleep(wait_time)
            self._refill()
            self._tokens -= tokens
            return wait_time

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Non-blocking acquire. Returns True if tokens available."""
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now

    @property
    def available(self) -> float:
        self._refill()
        return self._tokens


class RateLimiter:
    """
    Dual-bucket rate limiter for Kalshi API.

    Separate limits for read and write operations, matching Kalshi's tier system.
    """

    def __init__(self, read_per_sec: int = 20, write_per_sec: int = 10):
        self.read_bucket = TokenBucket(rate=read_per_sec)
        self.write_bucket = TokenBucket(rate=write_per_sec)
        log.info(
            "rate_limiter_initialized",
            read_per_sec=read_per_sec,
            write_per_sec=write_per_sec,
        )

    async def acquire_read(self) -> float:
        """Acquire a read token. Returns wait time."""
        wait = await self.read_bucket.acquire()
        if wait > 0:
            log.debug("rate_limit_wait", bucket="read", wait_ms=round(wait * 1000, 1))
        return wait

    async def acquire_write(self, tokens: float = 1.0) -> float:
        """Acquire write token(s). Batch operations may use fractional tokens."""
        wait = await self.write_bucket.acquire(tokens)
        if wait > 0:
            log.debug("rate_limit_wait", bucket="write", wait_ms=round(wait * 1000, 1))
        return wait
