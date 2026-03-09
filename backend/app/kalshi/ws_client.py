"""
JA Hedge — Kalshi WebSocket Client.

Real-time streaming client with:
- Auto-reconnect with exponential backoff
- Channel subscription management (orderbook, ticker, trade, fill)
- Message parsing into typed models
- Heartbeat/ping-pong keepalive
- Auth via RSA-PSS signed handshake

Kalshi WS Protocol (v2):
  - Connect to wss://...
  - First message: auth command with signed headers
  - Subscribe to channels: orderbook_delta, ticker, trade, fill
  - Receive real-time updates as JSON messages
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import orjson

from app.kalshi.auth import KalshiAuth, NoAuth
from app.logging_config import get_logger

log = get_logger("kalshi.ws")

# Try importing websockets; fall back gracefully
try:
    import websockets
    from websockets.asyncio.client import ClientConnection

    HAS_WEBSOCKETS = True
except ImportError:
    HAS_WEBSOCKETS = False
    ClientConnection = Any  # type: ignore[assignment, misc]


class WSChannel(str, Enum):
    """Kalshi WebSocket subscription channels."""

    ORDERBOOK_DELTA = "orderbook_delta"
    TICKER = "ticker"
    TRADE = "trade"
    FILL = "fill"
    ORDER_UPDATE = "order_update"


@dataclass
class WSMessage:
    """Parsed WebSocket message."""

    channel: str
    type: str  # "delta", "snapshot", "fill", "trade", etc.
    sid: int | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> WSMessage:
        return cls(
            channel=raw.get("type", raw.get("channel", "unknown")),
            type=raw.get("msg_type", raw.get("type", "unknown")),
            sid=raw.get("sid"),
            data=raw,
            timestamp=time.time(),
        )


# Type alias for message handlers
MessageHandler = Callable[[WSMessage], Coroutine[Any, Any, None]]


class KalshiWebSocket:
    """
    Async WebSocket client for Kalshi real-time data.

    Usage:
        ws = KalshiWebSocket(
            url="wss://demo-api.kalshi.co/trade-api/ws/v2",
            auth=kalshi_auth,
        )

        @ws.on(WSChannel.TICKER)
        async def on_ticker(msg: WSMessage):
            print(msg.data)

        await ws.connect()
        await ws.subscribe(WSChannel.TICKER, tickers=["KXBTC-24..."])
        # Messages flow to handlers automatically

        await ws.close()
    """

    def __init__(
        self,
        url: str,
        auth: KalshiAuth | NoAuth | None = None,
        *,
        max_reconnect_attempts: int = 20,
        reconnect_base_delay: float = 1.0,
        reconnect_max_delay: float = 60.0,
        ping_interval: float = 10.0,
        ping_timeout: float = 20.0,
    ):
        if not HAS_WEBSOCKETS:
            raise ImportError(
                "websockets package required. Install: pip install websockets"
            )

        self._url = url
        self._auth = auth or NoAuth()
        self._max_reconnect = max_reconnect_attempts
        self._reconnect_base = reconnect_base_delay
        self._reconnect_max = reconnect_max_delay
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout

        # State
        self._ws: ClientConnection | None = None
        self._connected = False
        self._should_run = False
        self._reconnect_count = 0
        self._last_message_time: float = 0

        # Subscriptions to re-subscribe on reconnect
        self._subscriptions: list[dict[str, Any]] = []

        # Message handlers per channel
        self._handlers: dict[str, list[MessageHandler]] = {}
        self._global_handlers: list[MessageHandler] = []

        # Background tasks
        self._receive_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    # ── Handler Registration ──────────────────────────────────────────────

    def on(self, channel: WSChannel | str) -> Callable:
        """
        Decorator to register a handler for a specific channel.

        @ws.on(WSChannel.TICKER)
        async def handle_ticker(msg: WSMessage):
            ...
        """
        ch = channel.value if isinstance(channel, WSChannel) else channel

        def decorator(func: MessageHandler) -> MessageHandler:
            self._handlers.setdefault(ch, []).append(func)
            return func

        return decorator

    def on_all(self, func: MessageHandler) -> MessageHandler:
        """Register a handler that receives ALL messages."""
        self._global_handlers.append(func)
        return func

    # ── Connection ────────────────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect to the WebSocket and start receiving messages."""
        self._should_run = True
        self._reconnect_count = 0
        await self._connect()

    async def _connect(self) -> None:
        """Internal connection logic."""
        try:
            # Build auth headers
            headers: dict[str, str] = {}
            if isinstance(self._auth, KalshiAuth):
                headers = self._auth.sign("GET", "/trade-api/ws/v2")

            self._ws = await websockets.connect(  # type: ignore[attr-defined]
                self._url,
                additional_headers=headers,
                ping_interval=self._ping_interval,
                ping_timeout=self._ping_timeout,
                max_size=10 * 1024 * 1024,  # 10MB max message
            )

            self._connected = True
            self._reconnect_count = 0
            self._last_message_time = time.time()
            log.info("ws_connected", url=self._url)

            # Re-subscribe to previous subscriptions
            for sub in self._subscriptions:
                await self._send(sub)

            # Start background tasks
            self._receive_task = asyncio.create_task(
                self._receive_loop(), name="ws_receive"
            )
            self._heartbeat_task = asyncio.create_task(
                self._heartbeat_loop(), name="ws_heartbeat"
            )

        except Exception as e:
            log.error("ws_connect_failed", error=str(e))
            self._connected = False
            if self._should_run:
                await self._reconnect()

    async def close(self) -> None:
        """Gracefully close the WebSocket connection."""
        self._should_run = False

        # Cancel background tasks
        for task in [self._receive_task, self._heartbeat_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close connection
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        self._connected = False
        log.info("ws_closed")

    # ── Subscriptions ─────────────────────────────────────────────────────

    async def subscribe(
        self,
        channel: WSChannel | str,
        *,
        tickers: list[str] | None = None,
        market_tickers: list[str] | None = None,
    ) -> None:
        """
        Subscribe to a WebSocket channel.

        Args:
            channel: The channel to subscribe to
            tickers: Market tickers to subscribe to (for orderbook_delta, ticker, trade)
            market_tickers: Alias for tickers (Kalshi uses both conventions)
        """
        ch = channel.value if isinstance(channel, WSChannel) else channel
        params: list[str] = tickers or market_tickers or []

        msg = {
            "id": int(time.time() * 1000),
            "cmd": "subscribe",
            "params": {
                "channels": [ch],
            },
        }
        if params:
            msg["params"]["market_tickers"] = params  # type: ignore[assignment]

        # Track for re-subscribe on reconnect
        self._subscriptions.append(msg)
        await self._send(msg)
        log.info("ws_subscribed", channel=ch, tickers=params)

    async def unsubscribe(
        self,
        channel: WSChannel | str,
        *,
        tickers: list[str] | None = None,
    ) -> None:
        """Unsubscribe from a WebSocket channel."""
        ch = channel.value if isinstance(channel, WSChannel) else channel

        msg = {
            "id": int(time.time() * 1000),
            "cmd": "unsubscribe",
            "params": {
                "channels": [ch],
            },
        }
        if tickers:
            msg["params"]["market_tickers"] = tickers  # type: ignore[assignment]

        # Remove from tracked subscriptions
        self._subscriptions = [
            s
            for s in self._subscriptions
            if not (
                s.get("params", {}).get("channels") == [ch]
                and (not tickers or s.get("params", {}).get("market_tickers") == tickers)
            )
        ]

        await self._send(msg)
        log.info("ws_unsubscribed", channel=ch, tickers=tickers)

    # ── Internal Message Loop ─────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        """Main message receive loop."""
        try:
            async for raw_msg in self._ws:  # type: ignore[union-attr]
                self._last_message_time = time.time()

                try:
                    data = orjson.loads(raw_msg)
                except (orjson.JSONDecodeError, TypeError):
                    log.warning("ws_invalid_json", raw=str(raw_msg)[:200])
                    continue

                # Parse into typed message
                msg = WSMessage.from_raw(data)

                # Dispatch to handlers
                await self._dispatch(msg)

        except asyncio.CancelledError:
            return
        except websockets.exceptions.ConnectionClosed as e:  # type: ignore[attr-defined]
            log.warning("ws_connection_closed", code=e.code, reason=e.reason)
            self._connected = False
            if self._should_run:
                await self._reconnect()
        except Exception as e:
            log.error("ws_receive_error", error=str(e))
            self._connected = False
            if self._should_run:
                await self._reconnect()

    async def _dispatch(self, msg: WSMessage) -> None:
        """Dispatch a message to registered handlers."""
        # Channel-specific handlers
        handlers = self._handlers.get(msg.channel, [])
        for handler in handlers:
            try:
                await handler(msg)
            except Exception as e:
                log.error(
                    "ws_handler_error",
                    channel=msg.channel,
                    error=str(e),
                )

        # Global handlers
        for handler in self._global_handlers:
            try:
                await handler(msg)
            except Exception as e:
                log.error("ws_global_handler_error", error=str(e))

    async def _heartbeat_loop(self) -> None:
        """Monitor connection health and detect stale connections."""
        try:
            while self._should_run and self._connected:
                await asyncio.sleep(self._ping_interval)

                # Check if we've received any data recently
                stale = time.time() - self._last_message_time
                if stale > self._ping_timeout * 2:
                    log.warning("ws_stale_connection", stale_seconds=stale)
                    # Force reconnect
                    if self._ws:
                        await self._ws.close()
                    break

        except asyncio.CancelledError:
            return

    # ── Reconnection ──────────────────────────────────────────────────────

    async def _reconnect(self) -> None:
        """Reconnect with exponential backoff."""
        if not self._should_run:
            return

        self._reconnect_count += 1
        if self._reconnect_count > self._max_reconnect:
            log.error(
                "ws_max_reconnect_exceeded",
                max=self._max_reconnect,
            )
            self._should_run = False
            return

        delay = min(
            self._reconnect_base * (2 ** (self._reconnect_count - 1)),
            self._reconnect_max,
        )
        log.info(
            "ws_reconnecting",
            attempt=self._reconnect_count,
            delay=delay,
        )
        await asyncio.sleep(delay)

        # Cancel old tasks
        for task in [self._receive_task, self._heartbeat_task]:
            if task and not task.done():
                task.cancel()

        await self._connect()

    # ── Send ──────────────────────────────────────────────────────────────

    async def _send(self, data: dict[str, Any]) -> None:
        """Send a JSON message to the WebSocket."""
        if not self._ws or not self._connected:
            log.warning("ws_send_not_connected")
            return

        try:
            await self._ws.send(orjson.dumps(data))
        except Exception as e:
            log.error("ws_send_error", error=str(e))
            self._connected = False

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def reconnect_count(self) -> int:
        return self._reconnect_count

    @property
    def subscription_count(self) -> int:
        return len(self._subscriptions)
