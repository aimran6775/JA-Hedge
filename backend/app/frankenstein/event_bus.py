"""
Frankenstein — Event Bus. 🧟📡

Async pub/sub system for decoupled communication between Frankenstein's
modules.  Components publish events (MarketUpdate, OrderFill, TradeExecuted)
and subscribe to each other without direct references.

This is the backbone of the reactive architecture:
  Scanner publishes  → TradeExecuted  → OrderManager tracks it
  Resolver publishes → OutcomeResolved → Memory/Performance update
  OrderManager       → OrderFilled     → Capital allocator frees funds
  WebSocket data     → MarketUpdate    → Scanner reacts immediately
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

from app.logging_config import get_logger

log = get_logger("frankenstein.event_bus")


# ── Event Types ───────────────────────────────────────────────────────────

class EventType(str, Enum):
    """All event types in the Frankenstein system."""

    # Market data events (REST / batch)
    MARKET_UPDATE = "market_update"           # Orderbook/price change
    MARKET_SNAPSHOT = "market_snapshot"        # Full market data refresh
    ORDERBOOK_DELTA = "orderbook_delta"        # L2 orderbook change

    # Real-time WebSocket events (Phase 2)
    TICKER_UPDATE = "ticker_update"            # WS ticker: price/bid/ask changed
    BOOK_CHANGED = "book_changed"              # WS orderbook_delta: L2 book moved
    FILL_RECEIVED = "fill_received"            # WS fill: our order was filled
    TRADE_OBSERVED = "trade_observed"          # WS trade: someone traded on exchange
    SUBSCRIPTION_UPDATE = "subscription_update"# WS sub lifecycle: added/removed tickers

    # Trading events
    TRADE_EXECUTED = "trade_executed"          # Order placed successfully
    TRADE_REJECTED = "trade_rejected"          # Order rejected by risk/exchange
    TRADE_CANDIDATE = "trade_candidate"        # Candidate identified (pre-execution)

    # Order lifecycle events
    ORDER_PLACED = "order_placed"              # Limit order resting on book
    ORDER_FILLED = "order_filled"              # Order was filled (partially or fully)
    ORDER_CANCELLED = "order_cancelled"        # Order cancelled (stale/manual)
    ORDER_AMENDED = "order_amended"            # Order price/size amended
    ORDER_EXPIRED = "order_expired"            # Order expired (TIF)

    # Position events
    POSITION_OPENED = "position_opened"        # New position created
    POSITION_CLOSED = "position_closed"        # Position exited
    POSITION_UPDATE = "position_update"        # Position value changed

    # Outcome events
    OUTCOME_RESOLVED = "outcome_resolved"      # Trade won/lost/expired
    OUTCOME_WIN = "outcome_win"                # Trade resolved as WIN
    OUTCOME_LOSS = "outcome_loss"              # Trade resolved as LOSS

    # Model events
    MODEL_RETRAINED = "model_retrained"        # Champion/challenger promoted
    MODEL_DEGRADING = "model_degrading"        # Performance declining

    # System events
    CIRCUIT_BREAKER = "circuit_breaker"        # Trading halted
    SCAN_COMPLETE = "scan_complete"            # One scan cycle finished
    HEALTH_CHECK = "health_check"              # Periodic health status
    CAPITAL_FREED = "capital_freed"            # Capital available for redeployment


@dataclass
class Event:
    """A single event in the system."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    source: str = ""  # Which module published this

    def __repr__(self) -> str:
        return f"Event({self.type.value}, source={self.source}, keys={list(self.data.keys())})"


# Type alias for event handlers
EventHandler = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """
    Async event bus for Frankenstein's modular architecture.

    Usage:
        bus = EventBus()

        # Subscribe
        async def on_fill(event: Event):
            print(f"Filled: {event.data['ticker']}")
        bus.subscribe(EventType.ORDER_FILLED, on_fill)

        # Publish
        await bus.publish(Event(
            type=EventType.ORDER_FILLED,
            data={"ticker": "KXBTC-24...", "count": 3},
            source="order_manager",
        ))

    Features:
    - Multiple handlers per event type
    - Wildcard handlers (receive ALL events)
    - Error isolation (one handler crash doesn't block others)
    - Event history for debugging
    - Metrics per event type
    """

    def __init__(self, *, history_size: int = 500) -> None:
        # Handler registry: event_type → list of async handlers
        self._handlers: dict[EventType, list[EventHandler]] = defaultdict(list)
        # Wildcard handlers that receive every event
        self._global_handlers: list[EventHandler] = []
        # Event history (ring buffer)
        self._history: list[Event] = []
        self._history_size = history_size
        # Metrics
        self._event_counts: dict[str, int] = defaultdict(int)
        self._handler_errors: int = 0
        self._total_published: int = 0

        log.info("event_bus_created")

    # ── Subscribe ─────────────────────────────────────────────────────

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._handlers[event_type].append(handler)
        log.debug("event_bus_subscribe", event_type=event_type.value,
                  handler=handler.__qualname__)

    def subscribe_many(self, event_types: list[EventType], handler: EventHandler) -> None:
        """Register a handler for multiple event types."""
        for et in event_types:
            self.subscribe(et, handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a handler that receives ALL events."""
        self._global_handlers.append(handler)

    def unsubscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Remove a handler."""
        try:
            self._handlers[event_type].remove(handler)
        except ValueError:
            pass

    # ── Publish ───────────────────────────────────────────────────────

    async def publish(self, event: Event) -> None:
        """
        Publish an event to all subscribed handlers.

        Handlers are called concurrently but errors in one handler
        don't affect others.
        """
        self._total_published += 1
        self._event_counts[event.type.value] += 1

        # Store in history
        self._history.append(event)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]

        # Gather all handlers for this event
        handlers = list(self._handlers.get(event.type, []))
        handlers.extend(self._global_handlers)

        if not handlers:
            return

        # Fire all handlers concurrently
        tasks = [self._safe_call(handler, event) for handler in handlers]
        await asyncio.gather(*tasks)

    def publish_sync(self, event: Event) -> None:
        """
        Publish an event without awaiting handlers.

        Use this when you need to fire-and-forget from synchronous code.
        The event will be dispatched in the background.
        """
        self._total_published += 1
        self._event_counts[event.type.value] += 1

        self._history.append(event)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size:]

        handlers = list(self._handlers.get(event.type, []))
        handlers.extend(self._global_handlers)

        if handlers:
            for handler in handlers:
                asyncio.create_task(self._safe_call(handler, event))

    async def _safe_call(self, handler: EventHandler, event: Event) -> None:
        """Call a handler with error isolation."""
        try:
            await handler(event)
        except Exception as e:
            self._handler_errors += 1
            log.error(
                "event_handler_error",
                event=event.type.value,
                handler=handler.__qualname__,
                error=str(e),
            )

    # ── Query ─────────────────────────────────────────────────────────

    def recent_events(self, n: int = 50, event_type: EventType | None = None) -> list[Event]:
        """Get recent events, optionally filtered by type."""
        if event_type:
            filtered = [e for e in self._history if e.type == event_type]
            return filtered[-n:]
        return self._history[-n:]

    def stats(self) -> dict[str, Any]:
        """Event bus statistics."""
        return {
            "total_published": self._total_published,
            "handler_errors": self._handler_errors,
            "handler_count": sum(len(h) for h in self._handlers.values()) + len(self._global_handlers),
            "event_types_active": len([k for k, v in self._handlers.items() if v]),
            "event_counts": dict(self._event_counts),
            "history_size": len(self._history),
        }
