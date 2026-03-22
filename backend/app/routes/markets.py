"""
JA Hedge — Market data API routes (LIVE).

GET /api/markets          — List markets (live Kalshi + cache)
GET /api/markets/:ticker  — Single market detail
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.pipeline import market_cache
from app.state import state
from app.logging_config import get_logger

log = get_logger("routes.markets")

router = APIRouter(prefix="/markets", tags=["Markets"])


class MarketResponse(BaseModel):
    ticker: str
    event_ticker: str
    title: str | None = None
    subtitle: str | None = None
    category: str | None = None
    status: str = "active"
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    last_price: float | None = None
    volume: float | None = None
    open_interest: float | None = None
    spread: float | None = None
    midpoint: float | None = None
    close_time: str | None = None


class MarketsListResponse(BaseModel):
    markets: list[MarketResponse]
    total: int
    source: str = "cache"


def _market_to_response(m) -> MarketResponse:
    return MarketResponse(
        ticker=m.ticker,
        event_ticker=m.event_ticker,
        title=m.title,
        subtitle=m.subtitle,
        category=m.category,
        status=m.status.value if m.status else "active",
        yes_bid=float(m.yes_bid) if m.yes_bid is not None else None,
        yes_ask=float(m.yes_ask) if m.yes_ask is not None else None,
        no_bid=float(m.no_bid) if m.no_bid is not None else None,
        no_ask=float(m.no_ask) if m.no_ask is not None else None,
        last_price=float(m.last_price) if m.last_price is not None else None,
        volume=float(m.volume) if m.volume is not None else (float(m.volume_int) if m.volume_int is not None else None),
        open_interest=float(m.open_interest) if m.open_interest is not None else None,
        spread=float(m.spread) if m.spread is not None else None,
        midpoint=float(m.midpoint) if m.midpoint is not None else None,
        close_time=m.close_time.isoformat() if m.close_time else None,
    )


@router.get("", response_model=MarketsListResponse)
async def list_markets(
    category: str | None = Query(None),
    status: str | None = Query(None, description="active, closed, determined"),
    search: str | None = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0, ge=0),
) -> MarketsListResponse:
    """List markets — fetches live from Kalshi if cache is empty."""
    cached = market_cache.get_all()
    source = "cache"

    if not cached and state.kalshi_api:
        try:
            log.info("fetching_markets_live", limit=limit)
            from app.kalshi.models import MarketStatus as MS
            ms = MS(status) if status and status not in ("all", "active") else None
            live, _ = await state.kalshi_api.markets.list_markets(
                limit=min(limit + offset, 200), status=ms, category=category,
            )
            market_cache.upsert_many(live)
            cached = live
            source = "live"
            log.info("markets_fetched_live", count=len(cached))
        except Exception as e:
            log.error("live_market_fetch_failed", error=str(e))

    markets = cached
    if category and source == "cache":
        markets = [m for m in markets if m.category and m.category.lower() == category.lower()]
    if search:
        q = search.lower()
        markets = [
            m for m in markets
            if (m.title and q in m.title.lower())
            or (m.subtitle and q in m.subtitle.lower())
            or q in m.ticker.lower()
        ]
    if status and status != "all" and source == "cache":
        markets = [m for m in markets if m.status and m.status.value == status]

    # Sort by volume descending so high-activity markets appear first
    markets.sort(key=lambda m: m.volume or 0, reverse=True)

    total = len(markets)
    markets = markets[offset : offset + limit]
    return MarketsListResponse(
        markets=[_market_to_response(m) for m in markets],
        total=total,
        source=source,
    )


@router.get("/{ticker}", response_model=MarketResponse)
async def get_market(ticker: str) -> MarketResponse:
    """Get a single market — cache first, then live Kalshi."""
    m = market_cache.get(ticker)
    if m:
        return _market_to_response(m)
    if state.kalshi_api:
        try:
            m = await state.kalshi_api.markets.get_market(ticker)
            market_cache.upsert(m)
            return _market_to_response(m)
        except Exception as e:
            log.error("market_get_failed", ticker=ticker, error=str(e))
    raise HTTPException(status_code=404, detail=f"Market {ticker} not found")
