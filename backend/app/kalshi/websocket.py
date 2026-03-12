"""
JA Hedge — Kalshi WebSocket Client (Phase 5).

Real-time data feeds via Kalshi WebSocket API v2:

Channels:
  1. ticker        — live price updates (yes_bid, yes_ask, last_price)
  2. orderbook_delta — full orderbook L2 changes
  3. trade          — every trade on the exchange
  4. fill           — our fills (requires auth)
  5. market_positions — our position changes (requires auth)

Architecture:
  - Single persistent connection with auto-reconnect
  - Event-driven callbacks for each channel
  - Feeds directly into FeatureEngine and market_cache
  - Heartbeat monitoring with stale-data detection
"""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any, Callable, Coroutine

from app.logging_config import get_logger

log = get_logger("kalshi.websocket")

# Type for async callbacks
WSCallback = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class KalshiWebSocket:
    """
    Persistent WebSocket connection to Kalshi real-time data feeds.

    Usage:
        ws = KalshiWebSocket(ws_url, auth_token)
        ws.on_ticker(my_callback)
        ws.on_trade(my_trade_callback)
        await ws.connect()
        await ws.subscribe_tickers(["TICKER1", "TICKER2"])
    """

    # Kalshi WS channels
    CHANNEL_TICKER = "ticker"
    CHANNEL_ORDERBOOK = "orderbook_delta"
    CHANNEL_TRADE = "trade"
    CHANNEL_FILL = "fill"

    def __init__(
        self,
        ws_url: str,
        auth_token: str | None = None,
        *,
        heartbeat_interval: float = 10.0,
        reconnect_delay: float = 5.0,
        max_reconnect_delay: float = 60.0,
    ):
        self._ws_url = ws_url
        self._auth_token = auth_token
        self._heartbeat_interval = heartbeat_interval
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_delay = max_reconnect_delay

        # State
        self._ws: Any = None
        self._connected = False
        self._running = False
        self._subscriptions: dict[str, set[str]] = defaultdict(set)
        self._last_message_time: float = 0
        self._reconnect_attempts: int = 0
        self._total_messages: int = 0

        # Callbacks per channel
        self._callbacks: dict[str, list[WSCallback]] = defaultdict(list)

        # Background tasks
        self._recv_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    # ── Event Registration ────────────────────────────────────────────

    def on_ticker(self, callback: WSCallback) -> None:
        """Register callback for ticker (price) updates."""
        self._callbacks[self.CHANNEL_TICKER].append(callback)

    def on_orderbook(self, callback: WSCallback) -> None:
        """Register callback for orderbook delta updates."""
        self._callbacks[self.CHANNEL_ORDERBOOK].append(callback)

    def on_trade(self, callback: WSCallback) -> None:
        """Register callback for trade events."""
        self._callbacks[self.CHANNEL_TRADE].append(callback)

    def on_fill(self, callback: WSCallback) -> None:
        """Register callback for our fill events (requires auth)."""
        self._callbacks[self.CHANNEL_FILL].append(callback)

    # ── Connection Lifecycle ──────────────────────────────────────────

    async def connect(self) -> None:
        """Establish WebSocket connection with auto-reconnect."""
        self._running = True
        await self._connect()

    async def _connect(self) -> None:
        """Internal: establish a single WS connection."""
        try:
            import websockets
        except ImportError:
            log.warning("websockets package not installed, WS feeds disabled")
            return

        try:
            headers = {}
            if self._auth_token:
                headers["Authorization"] = f"Bearer {self._auth_token}"

            self._ws = await websockets.connect(
                self._ws_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
            )
            self._connected = True
            self._reconnect_attempts = 0
            self._last_message_time = time.time()

            log.info("ws_connected", url=self._ws_url)

            # Re-subscribe to all channels after reconnect
            await self._resubscribe()

            # Start receive loop and heartbeat
            self._recv_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        except Exception as e:
            log.error("ws_connect_failed", error=str(e))
            self._connected = False
            if self._running:
                await self._schedule_reconnect()

    async def disconnect(self) -> None:
        """Gracefully close the WebSocket."""
        self._running = False
        self._connected = False

        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass

        log.info("ws_disconnected", total_messages=self._total_messages)

    # ── Subscriptions ─────────────────────────────────────────────────

    async def subscribe_tickers(self, tickers: list[str]) -> None:
        """Subscribe to ticker (price) updates for given markets."""
        await self._subscribe(self.CHANNEL_TICKER, tickers)

    async def subscribe_orderbooks(self, tickers: list[str]) -> None:
        """Subscribe to orderbook delta updates."""
        await self._subscribe(self.CHANNEL_ORDERBOOK, tickers)

    async def subscribe_trades(self, tickers: list[str]) -> None:
        """Subscribe to trade events."""
        await self._subscribe(self.CHANNEL_TRADE, tickers)

    async def subscribe_fills(self) -> None:
        """Subscribe to our fill events (requires auth)."""
        await self._subscribe(self.CHANNEL_FILL, [])

    async def _subscribe(self, channel: str, tickers: list[str]) -> None:
        """Send subscription command to Kalshi WS."""
        self._subscriptions[channel].update(tickers)

        if not self._connected or not self._ws:
            return

        msg = {
            "id": int(time.time() * 1000),
            "cmd": "subscribe",
            "params": {
                "channels": [channel],
            },
        }
        if tickers:
            msg["params"]["market_tickers"] = tickers

        try:
            await self._ws.send(json.dumps(msg))
            log.debug("ws_subscribed", channel=channel, tickers=len(tickers))
        except Exception as e:
            log.error("ws_subscribe_failed", channel=channel, error=str(e))

    async def _resubscribe(self) -> None:
        """Re-subscribe to all channels after reconnect."""
        for channel, tickers in self._subscriptions.items():
            if tickers:
                await self._subscribe(channel, list(tickers))
            else:
                await self._subscribe(channel, [])

    # ── Receive Loop ──────────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        """Main message processing loop."""
        try:
            while self._running and self._ws:
                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=30.0)
                    self._last_message_time = time.time()
                    self._total_messages += 1

                    data = json.loads(raw)
                    await self._dispatch(data)

                except asyncio.TimeoutError:
                    # No message in 30s — check if connection is alive
                    if time.time() - self._last_message_time > 60:
                        log.warning("ws_stale_connection", last_msg_ago=f"{time.time() - self._last_message_time:.0f}s")
                        break
                except Exception as e:
                    if self._running:
                        log.error("ws_recv_error", error=str(e))
                        break
        except asyncio.CancelledError:
            return

        # Connection lost — reconnect if still running
        self._connected = False
        if self._running:
            await self._schedule_reconnect()

    async def _dispatch(self, data: dict[str, Any]) -> None:
        """Route incoming message to appropriate callbacks."""
        msg_type = data.get("type", "")
        channel = data.get("channel", msg_type)

        # Handle subscription confirmations
        if msg_type == "subscribed":
            log.debug("ws_subscription_confirmed", channel=data.get("channel"))
            return

        # Handle errors
        if msg_type == "error":
            log.error("ws_server_error", msg=data.get("msg", "unknown"))
            return

        # Dispatch to registered callbacks
        callbacks = self._callbacks.get(channel, [])
        for cb in callbacks:
            try:
                await cb(data)
            except Exception as e:
                log.error("ws_callback_error", channel=channel, error=str(e))

    # ── Heartbeat ─────────────────────────────────────────────────────

    async def _heartbeat_loop(self) -> None:
        """Periodic health check for the connection."""
        try:
            while self._running and self._connected:
                await asyncio.sleep(self._heartbeat_interval)

                if not self._ws or not self._connected:
                    break

                # Check for stale data
                elapsed = time.time() - self._last_message_time
                if elapsed > 120:  # 2 minutes without data
                    log.warning("ws_heartbeat_stale", elapsed=f"{elapsed:.0f}s")
                    # Force reconnect
                    try:
                        await self._ws.close()
                    except Exception:
                        pass
                    break
        except asyncio.CancelledError:
            return

    # ── Reconnect ─────────────────────────────────────────────────────

    async def _schedule_reconnect(self) -> None:
        """Exponential backoff reconnection (non-blocking)."""
        self._reconnect_attempts += 1
        delay = min(
            self._reconnect_delay * (2 ** min(self._reconnect_attempts - 1, 5)),
            self._max_reconnect_delay,
        )

        if self._reconnect_attempts > 5:
            log.warning("ws_reconnect_giving_up", attempts=self._reconnect_attempts,
                        hint="Falling back to REST polling")
            self._running = False
            return

        log.info("ws_reconnecting", attempt=self._reconnect_attempts, delay=f"{delay:.0f}s")
        # Non-blocking: schedule reconnect as a background task
        asyncio.create_task(self._reconnect_after(delay))

    async def _reconnect_after(self, delay: float) -> None:
        """Wait then attempt reconnection."""
        try:
            await asyncio.sleep(delay)
            if self._running:
                await self._connect()
        except asyncio.CancelledError:
            return
        except Exception as e:
            log.error("ws_reconnect_error", error=str(e))

    # ── Status ────────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    def stats(self) -> dict[str, Any]:
        """WebSocket connection statistics."""
        return {
            "connected": self._connected,
            "total_messages": self._total_messages,
            "subscriptions": {k: len(v) for k, v in self._subscriptions.items()},
            "reconnect_attempts": self._reconnect_attempts,
            "last_message_ago": f"{time.time() - self._last_message_time:.0f}s" if self._last_message_time else "never",
        }


class WSDataFeeder:
    """
    Bridges WebSocket data into FeatureEngine and market_cache.

    Transforms raw WS messages into feature engine updates,
    replacing the slower REST polling approach.
    """

    def __init__(
        self,
        feature_engine: Any,  # FeatureEngine
    ):
        self._features = feature_engine
        self._trade_counts: dict[str, int] = defaultdict(int)
        self._last_prices: dict[str, float] = {}

    async def handle_ticker(self, data: dict[str, Any]) -> None:
        """Process ticker update from WS."""
        msg = data.get("msg", data)
        ticker = msg.get("market_ticker", "")
        if not ticker:
            return

        # Extract prices (Kalshi sends cents or dollars depending on field)
        yes_bid = msg.get("yes_bid", 0)
        yes_ask = msg.get("yes_ask", 0)
        last = msg.get("last_price", 0)
        volume = msg.get("volume", 0)

        # Convert to fraction if in cents
        if yes_bid and yes_bid > 1:
            yes_bid /= 100
        if yes_ask and yes_ask > 1:
            yes_ask /= 100
        if last and last > 1:
            last /= 100

        mid = (yes_bid + yes_ask) / 2 if yes_bid and yes_ask else last
        if mid > 0:
            self._features.update(ticker, mid, float(volume or 0))
            self._last_prices[ticker] = mid

        # Update market_cache if available
        try:
            from app.pipeline import market_cache
            cached = market_cache.get(ticker)
            if cached:
                from decimal import Decimal
                if yes_bid:
                    cached.yes_bid = Decimal(str(yes_bid))
                if yes_ask:
                    cached.yes_ask = Decimal(str(yes_ask))
                if last:
                    cached.last_price = Decimal(str(last))
        except Exception:
            pass

    async def handle_trade(self, data: dict[str, Any]) -> None:
        """Process trade event from WS."""
        msg = data.get("msg", data)
        ticker = msg.get("market_ticker", "")
        if not ticker:
            return

        self._trade_counts[ticker] += 1
        price = msg.get("yes_price", 0)
        if price and price > 1:
            price /= 100
        count = msg.get("count", 0)

        # Feed into feature engine as a price update
        if price > 0:
            self._features.update(ticker, price, float(count))

    async def handle_fill(self, data: dict[str, Any]) -> None:
        """Process our fill events from WS."""
        msg = data.get("msg", data)
        log.info(
            "ws_fill_received",
            order_id=msg.get("order_id", ""),
            ticker=msg.get("market_ticker", ""),
            side=msg.get("side", ""),
            action=msg.get("action", ""),
            count=msg.get("count", 0),
            price=msg.get("yes_price", msg.get("no_price", 0)),
        )

    def stats(self) -> dict[str, Any]:
        return {
            "tracked_tickers": len(self._last_prices),
            "total_trades_seen": sum(self._trade_counts.values()),
            "top_active": dict(
                sorted(self._trade_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            ),
        }
