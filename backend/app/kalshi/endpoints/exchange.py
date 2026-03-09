"""
JA Hedge — Exchange endpoints.

Covers:
  GET /exchange/status     — Exchange status (is trading active?)
  GET /exchange/schedule   — Exchange schedule / maintenance windows
"""

from __future__ import annotations

from typing import Any

from app.kalshi.client import KalshiClient
from app.kalshi.models import ExchangeSchedule, ExchangeStatus
from app.logging_config import get_logger

log = get_logger("kalshi.endpoints.exchange")


class ExchangeAPI:
    """Typed wrappers for exchange-related Kalshi endpoints."""

    def __init__(self, client: KalshiClient):
        self._client = client

    async def get_status(self) -> ExchangeStatus:
        """Check if the exchange is active and trading is open."""
        resp = await self._client.get(
            "/exchange/status", authenticated=False
        )
        return ExchangeStatus.model_validate(resp)

    async def get_schedule(self) -> list[ExchangeSchedule]:
        """Get the exchange weekly schedule and maintenance windows."""
        resp = await self._client.get(
            "/exchange/schedule", authenticated=False
        )
        schedules = resp.get("schedule", [])
        return [ExchangeSchedule.model_validate(s) for s in schedules]

    async def is_trading_active(self) -> bool:
        """Quick check: is trading currently possible?"""
        status = await self.get_status()
        return status.exchange_active and status.trading_active
