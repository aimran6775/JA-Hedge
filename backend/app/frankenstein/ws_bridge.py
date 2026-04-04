"""
Frankenstein — WebSocket Bridge. 🧟🔌

Phase 2: Real-time event loop.

Bridges the Kalshi WebSocket feed into Frankenstein's EventBus,
replacing the 30-second poll-only architecture with a reactive
event-driven model.

Architecture:
    KalshiWebSocket ──► WSBridge ──► EventBus
         │                              │
    (raw WS msgs)              (typed Events)
                                        │
                         ┌──────────────┼───────────────┐
                         ▼              ▼               ▼
                    OrderManager    Scanner        FeatureEngine
                    (requotes)    (fast-path)      (price updates)

Channels consumed:
    ticker          → TICKER_UPDATE event   → FeatureEngine + Scanner
    orderbook_delta → BOOK_CHANGED event    → OrderManager (requote)
    trade           → TRADE_OBSERVED event  → Feature updates
    fill            → FILL_RECEIVED event   → OrderManager (fill tracking)

The bridge also maintains a per-ticker L1 book snapshot (best bid/ask)
used by OrderManager for requoting decisions.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.frankenstein.event_bus import Event, EventBus, EventType
from app.logging_config import get_logger

log = get_logger("frankenstein.ws_bridge")


# ── L1 Book Snapshot ──────────────────────────────────────────────────

@dataclass
class BookSnapshot:
    """Best bid/ask for a single ticker — updated by WS feed."""

    ticker: str
    yes_bid: float = 0.0
    yes_ask: float = 0.0
    no_bid: float = 0.0
    no_ask: float = 0.0
    last_price: float = 0.0
    volume: int = 0
    open_interest: int = 0
    updated_at: float = field(default_factory=time.time)

    @property
    def mid(self) -> float:
        if self.yes_bid > 0 and self.yes_ask > 0:
            return (self.yes_bid + self.yes_ask) / 2.0
        return self.last_price

    @property
    def spread_cents(self) -> int:
        if self.yes_bid > 0 and self.yes_ask > 0:
            return max(int((self.yes_ask - self.yes_bid) * 100), 0)
        return 99

    def age_seconds(self) -> float:
        return time.time() - self.updated_at


class WSBridge:
    """
    Bridges Kalshi WebSocket data into Frankenstein's EventBus.

    Responsibilities:
    1. Connect to Kalshi WS and subscribe to channels
    2. Parse raw messages into typed EventBus events
    3. Maintain per-ticker L1 book snapshots
    4. Feed FeatureEngine with real-time price updates
    5. Dynamically manage subscriptions as markets change

    Usage (called by brain.py):
        bridge = WSBridge(event_bus=bus, feature_engine=feat)
        await bridge.start(ws_url, auth)
        await bridge.subscribe_tickers(["KXBTC-24...", ...])
        # ... events flow automatically ...
        await bridge.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        feature_engine: Any = None,
        *,
        max_subscriptions: int = 500,
        requote_debounce_ms: float = 200.0,
    ) -> None:
        self._bus = event_bus
        self._features = feature_engine
        self._max_subs = max_subscriptions
        self._requote_debounce_ms = requote_debounce_ms

        # WebSocket client (created on start)
        self._ws: Any = None
        self._running = False

        # L1 book state per ticker
        self._books: dict[str, BookSnapshot] = {}

        # Subscription management
        self._subscribed_tickers: set[str] = set()

        # Metrics
        self._stats = {
            "ticker_updates": 0,
            "book_changes": 0,
            "trades_observed": 0,
            "fills_received": 0,
            "events_published": 0,
            "ws_errors": 0,
            "last_event_at": 0.0,
            "amend_triggers": 0,
        }

        # Debounce: don't fire BOOK_CHANGED for same ticker faster than debounce_ms
        self._last_book_event: dict[str, float] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start(
        self,
        ws_url: str,
        auth: Any = None,
        *,
        auth_token: str | None = None,
    ) -> None:
        """
        Start the WS bridge.

        Uses app.kalshi.websocket.KalshiWebSocket with RSA-PSS auth
        (the `auth` parameter should be a KalshiAuth instance) or
        falls back to Bearer token if `auth_token` is provided.
        """
        if self._running:
            log.warning("ws_bridge_already_running")
            return

        self._running = True

        try:
            from app.kalshi.websocket import KalshiWebSocket

            self._ws = KalshiWebSocket(
                ws_url=ws_url,
                auth_token=auth_token,
                auth=auth,  # RSA-PSS signer
                heartbeat_interval=10.0,
                reconnect_delay=3.0,
                max_reconnect_delay=30.0,
            )

            # Register handlers for each channel
            self._ws.on_ticker(self._handle_ticker)
            self._ws.on_orderbook(self._handle_orderbook)
            self._ws.on_trade(self._handle_trade)
            self._ws.on_fill(self._handle_fill)

            await self._ws.connect()

            # Subscribe to fills immediately (requires auth)
            if auth or auth_token:
                await self._ws.subscribe_fills()

            log.info("🧟🔌 WS_BRIDGE STARTED",
                     url=ws_url, auth=bool(auth or auth_token))

        except ImportError:
            log.warning("ws_bridge_no_websockets",
                        hint="pip install websockets — falling back to poll-only")
            self._running = False
        except Exception as e:
            # Phase 28: Detailed error logging for WS connection failures
            import traceback
            tb_str = traceback.format_exc()[-500:]
            log.error("ws_bridge_start_failed",
                      error=str(e),
                      error_type=type(e).__name__,
                      ws_url=ws_url,
                      has_auth=bool(auth or auth_token),
                      traceback=tb_str,
                      hint="WS failed — system will use poll-only mode. Check ws_url and auth config.")
            self._running = False

    async def stop(self) -> None:
        """Stop the WS bridge and close connection."""
        if not self._running:
            return

        self._running = False

        if self._ws:
            try:
                await self._ws.disconnect()
            except Exception:
                pass
            self._ws = None

        log.info("🧟🔌 WS_BRIDGE STOPPED",
                 stats=self._stats,
                 subscriptions=len(self._subscribed_tickers))

    # ── Subscription Management ───────────────────────────────────────

    async def subscribe_tickers(self, tickers: list[str]) -> None:
        """Subscribe to real-time data for given tickers."""
        if not self._ws or not self._running:
            return

        # Deduplicate and respect max
        new_tickers = [t for t in tickers if t not in self._subscribed_tickers]
        remaining_capacity = self._max_subs - len(self._subscribed_tickers)
        batch = new_tickers[:remaining_capacity]

        if not batch:
            return

        # Subscribe to ticker + orderbook channels for these markets
        await self._ws.subscribe_tickers(batch)
        await self._ws.subscribe_orderbooks(batch)
        await self._ws.subscribe_trades(batch)

        self._subscribed_tickers.update(batch)

        # Initialize book snapshots
        for t in batch:
            if t not in self._books:
                self._books[t] = BookSnapshot(ticker=t)

        # Publish subscription event
        await self._bus.publish(Event(
            type=EventType.SUBSCRIPTION_UPDATE,
            data={
                "added": batch,
                "total_subscriptions": len(self._subscribed_tickers),
            },
            source="ws_bridge",
        ))

        log.info("ws_bridge_subscribed",
                 new=len(batch), total=len(self._subscribed_tickers))

    async def unsubscribe_tickers(self, tickers: list[str]) -> None:
        """Unsubscribe from tickers no longer needed."""
        if not self._ws or not self._running:
            return

        for t in tickers:
            self._subscribed_tickers.discard(t)
            self._books.pop(t, None)
            self._last_book_event.pop(t, None)

        log.info("ws_bridge_unsubscribed",
                 removed=len(tickers), total=len(self._subscribed_tickers))

    async def refresh_subscriptions(self, active_tickers: list[str]) -> None:
        """
        Sync subscriptions with the current active market list.

        Called periodically (e.g., after each full scan) to:
        - Subscribe to new markets that entered the tradeable set
        - Unsubscribe from markets that are no longer active
        """
        current = set(active_tickers[:self._max_subs])
        to_add = current - self._subscribed_tickers
        to_remove = self._subscribed_tickers - current

        if to_add:
            await self.subscribe_tickers(list(to_add))
        if to_remove:
            await self.unsubscribe_tickers(list(to_remove))

    # ── WS Message Handlers ───────────────────────────────────────────

    async def _handle_ticker(self, data: dict[str, Any]) -> None:
        """
        Handle ticker (price) update from WS.

        Kalshi ticker message:
        {
            "type": "ticker",
            "msg": {
                "market_ticker": "KXBTC-24...",
                "yes_bid": 45,    # cents
                "yes_ask": 47,
                "last_price": 46,
                "volume": 1234,
                "open_interest": 567,
            }
        }
        """
        try:
            msg = data.get("msg", data)
            ticker = msg.get("market_ticker", "")
            if not ticker:
                return

            # Parse prices (Kalshi sends cents for bid/ask)
            yes_bid = msg.get("yes_bid", 0)
            yes_ask = msg.get("yes_ask", 0)
            last = msg.get("last_price", 0)
            volume = msg.get("volume", 0)
            oi = msg.get("open_interest", 0)

            # Normalize to fractions (0.0-1.0) if sent as cents
            if yes_bid and yes_bid > 1:
                yes_bid /= 100.0
            if yes_ask and yes_ask > 1:
                yes_ask /= 100.0
            if last and last > 1:
                last /= 100.0

            # Update L1 book
            book = self._books.get(ticker)
            if not book:
                book = BookSnapshot(ticker=ticker)
                self._books[ticker] = book

            old_bid = book.yes_bid
            old_ask = book.yes_ask

            if yes_bid:
                book.yes_bid = yes_bid
            if yes_ask:
                book.yes_ask = yes_ask
            if last:
                book.last_price = last
            if volume:
                book.volume = int(volume)
            if oi:
                book.open_interest = int(oi)
            book.no_bid = 1.0 - book.yes_ask if book.yes_ask > 0 else 0.0
            book.no_ask = 1.0 - book.yes_bid if book.yes_bid > 0 else 0.0
            book.updated_at = time.time()

            # Feed into FeatureEngine
            if self._features and book.mid > 0:
                spread = book.yes_ask - book.yes_bid if (book.yes_bid > 0 and book.yes_ask > 0) else 0.0
                self._features.update(ticker, book.mid, float(volume or 0), float(oi or 0), spread)

            # Update market_cache
            self._update_market_cache(ticker, book)

            self._stats["ticker_updates"] += 1
            self._stats["last_event_at"] = time.time()

            # Publish TICKER_UPDATE event
            await self._bus.publish(Event(
                type=EventType.TICKER_UPDATE,
                data={
                    "ticker": ticker,
                    "yes_bid": book.yes_bid,
                    "yes_ask": book.yes_ask,
                    "last_price": book.last_price,
                    "mid": book.mid,
                    "spread_cents": book.spread_cents,
                    "volume": book.volume,
                },
                source="ws_bridge",
            ))

            # If bid/ask moved, also fire BOOK_CHANGED (debounced)
            bid_moved = abs(old_bid - book.yes_bid) >= 0.005 if old_bid > 0 else False
            ask_moved = abs(old_ask - book.yes_ask) >= 0.005 if old_ask > 0 else False
            if bid_moved or ask_moved:
                await self._fire_book_changed(ticker, book, "ticker_price_move")

        except Exception as e:
            self._stats["ws_errors"] += 1
            log.error("ws_bridge_ticker_error", error=str(e))

    async def _handle_orderbook(self, data: dict[str, Any]) -> None:
        """
        Handle orderbook delta from WS.

        Fires BOOK_CHANGED event which triggers requoting in OrderManager.
        """
        try:
            msg = data.get("msg", data)
            ticker = msg.get("market_ticker", "")
            if not ticker:
                return

            # Extract best bid/ask from delta
            # Kalshi orderbook_delta format varies — extract what we can
            yes_bids = msg.get("yes", msg.get("yes_bids", []))
            no_bids = msg.get("no", msg.get("no_bids", []))

            # Update L1 from orderbook data if available
            book = self._books.get(ticker)
            if not book:
                book = BookSnapshot(ticker=ticker)
                self._books[ticker] = book

            # Parse the best levels from the delta
            if yes_bids and isinstance(yes_bids, list) and len(yes_bids) > 0:
                # yes_bids is list of [price_cents, count] — best bid is highest
                best_bid = max((lvl[0] for lvl in yes_bids if len(lvl) >= 2 and lvl[1] > 0), default=0)
                if best_bid > 0:
                    book.yes_bid = best_bid / 100.0 if best_bid > 1 else best_bid

            if no_bids and isinstance(no_bids, list) and len(no_bids) > 0:
                best_no_bid = max((lvl[0] for lvl in no_bids if len(lvl) >= 2 and lvl[1] > 0), default=0)
                if best_no_bid > 0:
                    # no_bid at X → yes_ask at (100-X)
                    book.yes_ask = 1.0 - (best_no_bid / 100.0 if best_no_bid > 1 else best_no_bid)

            book.no_bid = 1.0 - book.yes_ask if book.yes_ask > 0 else 0.0
            book.no_ask = 1.0 - book.yes_bid if book.yes_bid > 0 else 0.0
            book.updated_at = time.time()

            self._stats["book_changes"] += 1
            self._stats["last_event_at"] = time.time()

            # Fire debounced BOOK_CHANGED
            await self._fire_book_changed(ticker, book, "orderbook_delta")

        except Exception as e:
            self._stats["ws_errors"] += 1
            log.error("ws_bridge_orderbook_error", error=str(e))

    async def _handle_trade(self, data: dict[str, Any]) -> None:
        """Handle trade event from WS — someone traded on the exchange."""
        try:
            msg = data.get("msg", data)
            ticker = msg.get("market_ticker", "")
            if not ticker:
                return

            price = msg.get("yes_price", 0)
            if price and price > 1:
                price /= 100.0
            count = msg.get("count", 0)

            # Update last_price in book
            book = self._books.get(ticker)
            if book and price > 0:
                book.last_price = price
                book.updated_at = time.time()

            # Feed feature engine
            if self._features and price > 0:
                self._features.update(ticker, price, float(count))

            self._stats["trades_observed"] += 1
            self._stats["last_event_at"] = time.time()

            # Publish (fire-and-forget for trades to avoid backpressure)
            self._bus.publish_sync(Event(
                type=EventType.TRADE_OBSERVED,
                data={
                    "ticker": ticker,
                    "price": price,
                    "count": count,
                    "taker_side": msg.get("taker_side", ""),
                },
                source="ws_bridge",
            ))

        except Exception as e:
            self._stats["ws_errors"] += 1
            log.error("ws_bridge_trade_error", error=str(e))

    async def _handle_fill(self, data: dict[str, Any]) -> None:
        """
        Handle fill event from WS — OUR order was filled.

        This is the critical path for:
        - Updating pending_orders in OrderManager
        - Freeing reserved capital
        - Triggering CAPITAL_FREED events for redeployment
        """
        try:
            msg = data.get("msg", data)
            order_id = msg.get("order_id", "")
            ticker = msg.get("market_ticker", "")
            side = msg.get("side", "")
            action = msg.get("action", "")
            count = msg.get("count", 0)
            price = msg.get("yes_price", msg.get("no_price", 0))

            self._stats["fills_received"] += 1
            self._stats["last_event_at"] = time.time()

            log.info("🧟💰 FILL RECEIVED",
                     order_id=order_id, ticker=ticker,
                     side=side, action=action,
                     count=count, price=price)

            # Publish FILL_RECEIVED event
            await self._bus.publish(Event(
                type=EventType.FILL_RECEIVED,
                data={
                    "order_id": order_id,
                    "ticker": ticker,
                    "side": side,
                    "action": action,
                    "count": count,
                    "price_cents": price,
                    "is_maker": msg.get("is_maker", True),
                },
                source="ws_bridge",
            ))

        except Exception as e:
            self._stats["ws_errors"] += 1
            log.error("ws_bridge_fill_error", error=str(e))

    # ── Book Changed (debounced) ──────────────────────────────────────

    async def _fire_book_changed(
        self,
        ticker: str,
        book: BookSnapshot,
        trigger: str,
    ) -> None:
        """
        Publish BOOK_CHANGED event with debouncing.

        We debounce to prevent flooding the EventBus when a ticker
        gets rapid-fire updates (e.g., during a sweep). The requoter
        only needs the latest state, not every intermediate tick.
        """
        now_ms = time.time() * 1000
        last = self._last_book_event.get(ticker, 0.0)

        if now_ms - last < self._requote_debounce_ms:
            return  # Skip — too soon since last event for this ticker

        self._last_book_event[ticker] = now_ms
        self._stats["amend_triggers"] += 1
        self._stats["events_published"] += 1

        await self._bus.publish(Event(
            type=EventType.BOOK_CHANGED,
            data={
                "ticker": ticker,
                "yes_bid": book.yes_bid,
                "yes_ask": book.yes_ask,
                "no_bid": book.no_bid,
                "no_ask": book.no_ask,
                "mid": book.mid,
                "spread_cents": book.spread_cents,
                "trigger": trigger,
            },
            source="ws_bridge",
        ))

    # ── Cache Integration ─────────────────────────────────────────────

    @staticmethod
    def _update_market_cache(ticker: str, book: BookSnapshot) -> None:
        """Push L1 updates into the global market_cache."""
        try:
            from app.pipeline import market_cache
            cached = market_cache.get(ticker)
            if not cached:
                return
            from decimal import Decimal
            if book.yes_bid > 0:
                cached.yes_bid = Decimal(str(round(book.yes_bid, 2)))
            if book.yes_ask > 0:
                cached.yes_ask = Decimal(str(round(book.yes_ask, 2)))
            if book.last_price > 0:
                cached.last_price = Decimal(str(round(book.last_price, 2)))
            # Recompute midpoint
            if book.yes_bid > 0 and book.yes_ask > 0:
                cached.midpoint = Decimal(str(round(book.mid, 4)))
                cached.spread = Decimal(str(round(book.yes_ask - book.yes_bid, 4)))
        except Exception:
            pass

    # ── Query / Status ────────────────────────────────────────────────

    def get_book(self, ticker: str) -> BookSnapshot | None:
        """Get the latest L1 book snapshot for a ticker."""
        return self._books.get(ticker)

    def get_all_books(self) -> dict[str, BookSnapshot]:
        """Get all tracked book snapshots."""
        return dict(self._books)

    @property
    def is_connected(self) -> bool:
        return self._running and self._ws is not None and getattr(self._ws, "is_connected", False)

    @property
    def subscription_count(self) -> int:
        return len(self._subscribed_tickers)

    def stats(self) -> dict[str, Any]:
        """Bridge statistics for status API."""
        now = time.time()
        freshness = {
            "fresh_1s": sum(1 for b in self._books.values() if b.age_seconds() < 1),
            "fresh_5s": sum(1 for b in self._books.values() if b.age_seconds() < 5),
            "fresh_30s": sum(1 for b in self._books.values() if b.age_seconds() < 30),
            "stale_60s": sum(1 for b in self._books.values() if b.age_seconds() > 60),
        }

        return {
            "running": self._running,
            "connected": self.is_connected,
            "subscriptions": len(self._subscribed_tickers),
            "tracked_books": len(self._books),
            "freshness": freshness,
            "ws_stats": self._ws.stats() if self._ws and hasattr(self._ws, "stats") else {},
            **self._stats,
        }
