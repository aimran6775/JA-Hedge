"""
JA Hedge — Alerts & Notification System.

Real-time alerts for:
- Trade executions / fills
- Risk violations (daily loss, position limits, kill switch)
- Strategy signals (executed, filtered, rejected)
- Market events (price moves, expiry approaching)
- System events (connection lost, reconnect)

Delivery channels:
- In-app (WebSocket push to dashboard)
- Logged to DB for history
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from app.logging_config import get_logger

log = get_logger("alerts")


class AlertLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AlertCategory(str, Enum):
    TRADE = "trade"
    RISK = "risk"
    STRATEGY = "strategy"
    MARKET = "market"
    SYSTEM = "system"


@dataclass
class Alert:
    """A single alert event."""

    id: str
    level: AlertLevel
    category: AlertCategory
    title: str
    message: str
    timestamp: float = field(default_factory=time.time)
    data: dict[str, Any] = field(default_factory=dict)
    read: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level.value,
            "category": self.category.value,
            "title": self.title,
            "message": self.message,
            "timestamp": self.timestamp,
            "iso_time": datetime.fromtimestamp(self.timestamp, tz=timezone.utc).isoformat(),
            "data": self.data,
            "read": self.read,
        }


class AlertManager:
    """
    Central alert manager.

    Collects alerts from all subsystems, stores them in memory
    (ring buffer), and notifies subscribed listeners (e.g., WebSocket).
    """

    MAX_ALERTS = 500  # rolling window

    def __init__(self):
        self._alerts: list[Alert] = []
        self._counter = 0
        self._listeners: list[Callable[[Alert], Any]] = []
        self._lock = asyncio.Lock()

    @property
    def alerts(self) -> list[Alert]:
        return list(self._alerts)

    @property
    def unread_count(self) -> int:
        return sum(1 for a in self._alerts if not a.read)

    def subscribe(self, callback: Callable[[Alert], Any]) -> None:
        """Register a listener called on every new alert."""
        self._listeners.append(callback)

    def unsubscribe(self, callback: Callable[[Alert], Any]) -> None:
        self._listeners = [l for l in self._listeners if l is not callback]

    async def emit(
        self,
        level: AlertLevel,
        category: AlertCategory,
        title: str,
        message: str,
        data: dict[str, Any] | None = None,
    ) -> Alert:
        """Create and dispatch a new alert."""
        async with self._lock:
            self._counter += 1
            alert = Alert(
                id=f"alert_{self._counter}",
                level=level,
                category=category,
                title=title,
                message=message,
                data=data or {},
            )
            self._alerts.append(alert)

            # Trim old alerts
            if len(self._alerts) > self.MAX_ALERTS:
                self._alerts = self._alerts[-self.MAX_ALERTS :]

        # Log
        log_fn = {
            AlertLevel.INFO: log.info,
            AlertLevel.WARNING: log.warning,
            AlertLevel.ERROR: log.error,
            AlertLevel.CRITICAL: log.critical,
        }.get(level, log.info)
        log_fn("alert_emitted", title=title, category=category.value, level=level.value)

        # Notify listeners (fire and forget)
        for listener in self._listeners:
            try:
                result = listener(alert)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as e:
                log.error("alert_listener_error", error=str(e))

        return alert

    def mark_read(self, alert_id: str) -> bool:
        for a in self._alerts:
            if a.id == alert_id:
                a.read = True
                return True
        return False

    def mark_all_read(self) -> int:
        count = 0
        for a in self._alerts:
            if not a.read:
                a.read = True
                count += 1
        return count

    def get_recent(
        self,
        limit: int = 50,
        category: AlertCategory | None = None,
        level: AlertLevel | None = None,
    ) -> list[Alert]:
        """Get recent alerts with optional filtering."""
        filtered = self._alerts
        if category:
            filtered = [a for a in filtered if a.category == category]
        if level:
            filtered = [a for a in filtered if a.level == level]
        return filtered[-limit:]

    # ── Convenience methods ───────────────────────────────

    async def trade_executed(
        self, ticker: str, side: str, count: int, price: int, order_id: str
    ) -> Alert:
        return await self.emit(
            AlertLevel.INFO,
            AlertCategory.TRADE,
            f"Order Executed: {ticker}",
            f"{side.upper()} {count}x @ {price}¢",
            data={"ticker": ticker, "side": side, "count": count, "price": price, "order_id": order_id},
        )

    async def trade_failed(self, ticker: str, reason: str) -> Alert:
        return await self.emit(
            AlertLevel.ERROR,
            AlertCategory.TRADE,
            f"Order Failed: {ticker}",
            reason,
            data={"ticker": ticker},
        )

    async def risk_violation(self, violation_type: str, message: str, severity: str = "warning") -> Alert:
        level = AlertLevel.CRITICAL if severity == "critical" else AlertLevel.WARNING
        return await self.emit(
            level,
            AlertCategory.RISK,
            f"Risk: {violation_type}",
            message,
            data={"violation_type": violation_type},
        )

    async def kill_switch_activated(self, reason: str) -> Alert:
        return await self.emit(
            AlertLevel.CRITICAL,
            AlertCategory.RISK,
            "🛑 Kill Switch Activated",
            reason,
            data={"action": "kill_switch"},
        )

    async def strategy_signal(
        self, ticker: str, side: str, confidence: float, edge: float, action: str
    ) -> Alert:
        return await self.emit(
            AlertLevel.INFO,
            AlertCategory.STRATEGY,
            f"Signal: {ticker} {side.upper()}",
            f"Conf={confidence:.0%} Edge={edge:.1%} → {action}",
            data={"ticker": ticker, "side": side, "confidence": confidence, "edge": edge, "action": action},
        )

    async def system_event(self, title: str, message: str, level: AlertLevel = AlertLevel.INFO) -> Alert:
        return await self.emit(level, AlertCategory.SYSTEM, title, message)


# Singleton
alert_manager = AlertManager()
