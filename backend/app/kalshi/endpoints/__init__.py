"""
JA Hedge — Kalshi REST Endpoint Wrappers.

Typed, high-level methods for every Kalshi API endpoint.
"""

from app.kalshi.endpoints.markets import MarketsAPI
from app.kalshi.endpoints.portfolio import PortfolioAPI
from app.kalshi.endpoints.orders import OrdersAPI
from app.kalshi.endpoints.exchange import ExchangeAPI
from app.kalshi.endpoints.historical import HistoricalAPI

__all__ = [
    "MarketsAPI",
    "PortfolioAPI",
    "OrdersAPI",
    "ExchangeAPI",
    "HistoricalAPI",
]
