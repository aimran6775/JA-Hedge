"""
JA Hedge — Market Data Pipeline.

Periodic polling + WebSocket real-time data ingestion:
- Snapshot market prices into TimescaleDB
- Maintain in-memory market cache for fast lookups
- Feed price data to AI feature engineering
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_session_factory
from app.db.models import MarketRecord, PriceSnapshot
from app.kalshi.api import KalshiAPI
from app.kalshi.models import Market, MarketStatus
from app.kalshi.ws_client import KalshiWebSocket, WSChannel, WSMessage
from app.logging_config import get_logger

log = get_logger("pipeline.market_data")


class MarketCache:
    """
    In-memory market cache for sub-millisecond lookups.

    Updated by both the polling loop and WebSocket ticker channel.
    Note: Not thread-safe — designed for single-threaded asyncio use.
    """

    def __init__(self) -> None:
        self._markets: dict[str, Market] = {}
        self._last_update: float = 0

    def upsert(self, market: Market) -> None:
        self._markets[market.ticker] = market
        self._last_update = time.time()

    def upsert_many(self, markets: list[Market]) -> None:
        for m in markets:
            self._markets[m.ticker] = m
        self._last_update = time.time()

    def get(self, ticker: str) -> Market | None:
        return self._markets.get(ticker)

    def get_all(self) -> list[Market]:
        return list(self._markets.values())

    def get_active(self) -> list[Market]:
        # Kalshi API returns "open"; ACTIVE is a legacy alias — accept both
        return [
            m for m in self._markets.values()
            if m.status in (MarketStatus.ACTIVE, MarketStatus.OPEN)
        ]

    def get_by_event(self, event_ticker: str) -> list[Market]:
        return [m for m in self._markets.values() if m.event_ticker == event_ticker]

    def get_sports(self) -> list[Market]:
        """Get all active sports markets using the sports detector."""
        try:
            from app.sports.detector import sports_detector
            active = self.get_active()
            return sports_detector.filter_sports(active)
        except ImportError:
            return []

    @property
    def count(self) -> int:
        return len(self._markets)

    @property
    def last_update(self) -> float:
        return self._last_update


# Global market cache singleton
market_cache = MarketCache()


class MarketDataPipeline:
    """
    Orchestrates market data collection via REST polling + WebSocket.

    1. Full refresh: Polls all active markets every N seconds
    2. Snapshots: Stores price snapshots in TimescaleDB
    3. Real-time: WebSocket ticker channel updates the cache
    """

    def __init__(
        self,
        api: KalshiAPI,
        ws: KalshiWebSocket | None = None,
        *,
        poll_interval: float = 45.0,  # 45s — paginating 70+ pages is slow
        snapshot_interval: float = 60.0,
        on_refresh_callback: Any | None = None,
    ):
        self._api = api
        self._ws = ws
        self._poll_interval = poll_interval
        self._snapshot_interval = snapshot_interval
        self._on_refresh_callback = on_refresh_callback
        self._running = False
        self._poll_task: asyncio.Task | None = None
        self._snapshot_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the market data pipeline."""
        self._running = True

        # Initial full load
        await self._full_refresh()

        # Start background tasks
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name="market_poll"
        )
        self._snapshot_task = asyncio.create_task(
            self._snapshot_loop(), name="market_snapshot"
        )

        # Setup WebSocket handlers if available
        if self._ws:
            self._ws.on(WSChannel.TICKER)(self._on_ticker_update)

        log.info(
            "market_pipeline_started",
            poll_interval=self._poll_interval,
            snapshot_interval=self._snapshot_interval,
            cached_markets=market_cache.count,
        )

    async def stop(self) -> None:
        """Stop the pipeline gracefully."""
        self._running = False
        for task in [self._poll_task, self._snapshot_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        log.info("market_pipeline_stopped")

    async def _full_refresh(self) -> None:
        """Fetch all active markets from REST API and update cache + DB."""
        try:
            all_markets = await self._api.markets.get_all_markets(
                status=MarketStatus.ACTIVE
            )

            # Filter out MVE parlay markets — they outnumber individual markets
            # ~10:1 and drown out the cache.  All MVE tickers start with KXMVE.
            # We keep individual markets (sports, crypto, politics, weather, etc.)
            _MVE_PREFIXES = ("KXMVE", "KXMVECROSSCATEGORY", "KXMVESPORTS")
            markets = [
                m for m in all_markets
                if not (m.ticker or "").upper().startswith(_MVE_PREFIXES)
            ]

            market_cache.upsert_many(markets)
            await self._upsert_markets_to_db(markets)

            # Feed FeatureEngine with fresh price data
            if self._on_refresh_callback:
                try:
                    self._on_refresh_callback(markets)
                except Exception as cb_err:
                    log.debug("refresh_callback_error", error=str(cb_err))

            log.info(
                "market_full_refresh",
                total_from_api=len(all_markets),
                mve_filtered=len(all_markets) - len(markets),
                individual_cached=len(markets),
            )
        except Exception as e:
            log.error("market_refresh_failed", error=str(e))

    async def _poll_loop(self) -> None:
        """Periodically refresh market data."""
        try:
            while self._running:
                await asyncio.sleep(self._poll_interval)
                await self._full_refresh()
        except asyncio.CancelledError:
            return

    async def _snapshot_loop(self) -> None:
        """Periodically store price snapshots for AI features."""
        try:
            while self._running:
                await asyncio.sleep(self._snapshot_interval)
                await self._take_snapshots()
        except asyncio.CancelledError:
            return

    async def _take_snapshots(self) -> None:
        """Snapshot all cached market prices into TimescaleDB."""
        markets = market_cache.get_active()
        if not markets:
            return

        now = datetime.now(timezone.utc)
        snapshots = []
        for m in markets:
            snapshots.append(
                {
                    "ticker": m.ticker,
                    "ts": now,
                    "yes_bid": m.yes_bid,
                    "yes_ask": m.yes_ask,
                    "last_price": m.last_price,
                    "volume": m.volume,
                    "open_interest": m.open_interest,
                    "spread": m.spread,
                    "midpoint": m.midpoint,
                }
            )

        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                await session.execute(
                    PriceSnapshot.__table__.insert(),  # type: ignore[arg-type]
                    snapshots,
                )
                await session.commit()
            log.debug("snapshots_stored", count=len(snapshots))
        except Exception as e:
            log.error("snapshot_store_failed", error=str(e))

    async def _upsert_markets_to_db(self, markets: list[Market]) -> None:
        """Upsert market data into the markets table."""
        if not markets:
            return

        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                for m in markets:
                    stmt = pg_insert(MarketRecord).values(
                        ticker=m.ticker,
                        event_ticker=m.event_ticker,
                        series_ticker=m.series_ticker,
                        title=m.title,
                        subtitle=m.subtitle,
                        category=m.category,
                        market_type=m.market_type.value if m.market_type else "binary",
                        status=m.status.value if m.status else "active",
                        yes_bid=m.yes_bid,
                        yes_ask=m.yes_ask,
                        no_bid=m.no_bid,
                        no_ask=m.no_ask,
                        last_price=m.last_price,
                        volume=m.volume,
                        open_interest=m.open_interest,
                        open_time=m.open_time,
                        close_time=m.close_time,
                        expiration_time=m.expiration_time,
                    ).on_conflict_do_update(
                        index_elements=["ticker"],
                        set_={
                            "status": m.status.value if m.status else "active",
                            "yes_bid": m.yes_bid,
                            "yes_ask": m.yes_ask,
                            "no_bid": m.no_bid,
                            "no_ask": m.no_ask,
                            "last_price": m.last_price,
                            "volume": m.volume,
                            "open_interest": m.open_interest,
                        },
                    )
                    await session.execute(stmt)
                await session.commit()
        except Exception as e:
            log.error("market_db_upsert_failed", error=str(e))

    async def _on_ticker_update(self, msg: WSMessage) -> None:
        """Handle real-time ticker updates from WebSocket."""
        data = msg.data
        ticker = data.get("market_ticker") or data.get("ticker")
        if not ticker:
            return

        # Update the in-memory cache with new price data
        existing = market_cache.get(ticker)
        if existing:
            # Patch the existing market with new fields
            if "yes_bid" in data:
                existing.yes_bid = Decimal(str(data["yes_bid"]))
            if "yes_ask" in data:
                existing.yes_ask = Decimal(str(data["yes_ask"]))
            if "last_price" in data:
                existing.last_price = Decimal(str(data["last_price"]))
            if "volume" in data:
                existing.volume = Decimal(str(data["volume"]))
            market_cache.upsert(existing)
