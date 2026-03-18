"""
Phase 15 — Real-time Alert Pipeline.

Watches all intelligence sources for significant signals and emits
structured alerts that can be:
  1. Surfaced on the dashboard
  2. Forwarded to the Frankenstein brain for immediate action
  3. Logged for historical analysis

Alert types:
  • SIGNAL_SPIKE    — a source's signal jumps dramatically
  • SOURCE_AGREE    — multiple sources converge on a strong signal
  • NEW_OPPORTUNITY — new high-edge opportunity discovered
  • SOURCE_DOWN     — a data source has gone unhealthy
  • QUALITY_WARN    — data quality issue detected
  • MARKET_MOVE     — large market movement detected
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from app.logging_config import get_logger

log = get_logger("intelligence.alerts")


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    SIGNAL_SPIKE = "signal_spike"
    SOURCE_AGREE = "source_agree"
    NEW_OPPORTUNITY = "new_opportunity"
    SOURCE_DOWN = "source_down"
    QUALITY_WARN = "quality_warn"
    MARKET_MOVE = "market_move"
    TREND_DETECTED = "trend_detected"


@dataclass
class Alert:
    """A structured alert from the intelligence system."""
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    source_name: str = ""
    category: str = ""
    ticker: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    acknowledged: bool = False

    def to_dict(self) -> dict:
        return {
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "message": self.message,
            "source_name": self.source_name,
            "category": self.category,
            "ticker": self.ticker,
            "data": self.data,
            "timestamp": self.timestamp,
            "acknowledged": self.acknowledged,
        }


# Type alias for alert handlers
AlertHandler = Callable[[Alert], Awaitable[None]]


class AlertPipeline:
    """
    Monitors intelligence sources and emits structured alerts.

    Integrates with DataSourceHub to watch for:
    - Signal spikes across sources
    - Multi-source agreement
    - Source health changes
    - Data quality issues
    """

    def __init__(
        self,
        max_alerts: int = 1000,
        spike_threshold: float = 0.4,   # signal change > 0.4 = spike
        agreement_threshold: int = 3,    # ≥ 3 sources agree = alert
        agreement_strength: float = 0.3, # minimum signal strength for agreement
    ) -> None:
        self._alerts: deque[Alert] = deque(maxlen=max_alerts)
        self._handlers: list[AlertHandler] = []
        self._spike_threshold = spike_threshold
        self._agreement_threshold = agreement_threshold
        self._agreement_strength = agreement_strength

        # Track previous signal values for spike detection
        self._prev_signals: dict[str, dict[str, float]] = {}  # source → ticker → value

        # Dedup: avoid spamming the same alert
        self._recent_hashes: deque[str] = deque(maxlen=500)

        self._running = False
        self._task: asyncio.Task | None = None

    def register_handler(self, handler: AlertHandler) -> None:
        """Register an async callback for new alerts."""
        self._handlers.append(handler)

    async def _emit(self, alert: Alert) -> None:
        """Emit an alert to all handlers and store it."""
        # Dedup check
        h = f"{alert.alert_type}:{alert.source_name}:{alert.ticker}:{int(alert.timestamp / 60)}"
        if h in self._recent_hashes:
            return
        self._recent_hashes.append(h)

        self._alerts.appendleft(alert)
        log.info(
            "alert_emitted",
            alert_type=alert.alert_type.value,
            severity=alert.severity.value,
            title=alert.title,
            source=alert.source_name,
        )

        for handler in self._handlers:
            try:
                await handler(alert)
            except Exception:
                log.exception("alert_handler_error")

    async def check_signals(self, hub: Any) -> None:
        """Run one check cycle against the hub's current signals."""
        try:
            all_signals = hub.get_all_signals()
        except Exception:
            return

        # ── Signal spike detection ──
        for source_name, ticker_signals in all_signals.items():
            prev = self._prev_signals.get(source_name, {})
            for ticker, signal in ticker_signals.items():
                old_val = prev.get(ticker, 0.0)
                new_val = signal.signal_value
                delta = abs(new_val - old_val)

                if delta >= self._spike_threshold and abs(new_val) > 0.2:
                    direction = "bullish" if new_val > old_val else "bearish"
                    severity = AlertSeverity.CRITICAL if delta > 0.6 else AlertSeverity.WARNING
                    await self._emit(Alert(
                        alert_type=AlertType.SIGNAL_SPIKE,
                        severity=severity,
                        title=f"Signal spike: {source_name}",
                        message=f"{source_name} signal for {ticker or signal.category} jumped "
                                f"{delta:+.2f} ({direction}). Now at {new_val:+.2f}.",
                        source_name=source_name,
                        category=signal.category,
                        ticker=ticker,
                        data={"old": old_val, "new": new_val, "delta": delta},
                    ))

            # Update prev signals
            self._prev_signals[source_name] = {
                t: s.signal_value for t, s in ticker_signals.items()
            }

        # ── Multi-source agreement detection ──
        # Group signals by category
        category_signals: dict[str, list[tuple[str, float]]] = {}
        for source_name, ticker_signals in all_signals.items():
            for ticker, signal in ticker_signals.items():
                cat = signal.category or "general"
                if cat not in category_signals:
                    category_signals[cat] = []
                if abs(signal.signal_value) >= self._agreement_strength:
                    category_signals[cat].append((source_name, signal.signal_value))

        for category, source_vals in category_signals.items():
            if len(source_vals) < self._agreement_threshold:
                continue

            # Check if sources agree on direction
            positive = [s for s, v in source_vals if v > 0]
            negative = [s for s, v in source_vals if v < 0]

            if len(positive) >= self._agreement_threshold:
                avg_signal = sum(v for _, v in source_vals if v > 0) / len(positive)
                await self._emit(Alert(
                    alert_type=AlertType.SOURCE_AGREE,
                    severity=AlertSeverity.WARNING,
                    title=f"Multi-source bullish: {category}",
                    message=f"{len(positive)} sources agree bullish on {category}: "
                            f"{', '.join(positive)}. Avg signal: {avg_signal:+.2f}",
                    category=category,
                    data={"direction": "bullish", "sources": positive, "avg_signal": avg_signal},
                ))

            if len(negative) >= self._agreement_threshold:
                avg_signal = sum(v for _, v in source_vals if v < 0) / len(negative)
                await self._emit(Alert(
                    alert_type=AlertType.SOURCE_AGREE,
                    severity=AlertSeverity.WARNING,
                    title=f"Multi-source bearish: {category}",
                    message=f"{len(negative)} sources agree bearish on {category}: "
                            f"{', '.join(negative)}. Avg signal: {avg_signal:+.2f}",
                    category=category,
                    data={"direction": "bearish", "sources": negative, "avg_signal": avg_signal},
                ))

        # ── Source health checks ──
        try:
            status = hub.status()
            for src in status.get("sources", []):
                if not src.get("healthy", True) and src.get("enabled", True):
                    await self._emit(Alert(
                        alert_type=AlertType.SOURCE_DOWN,
                        severity=AlertSeverity.CRITICAL,
                        title=f"Source unhealthy: {src['name']}",
                        message=f"{src['name']} is enabled but unhealthy. "
                                f"Errors: {src.get('error_count', 0)}, "
                                f"Last fetch: {src.get('last_fetch_seconds_ago', 'N/A')}s ago.",
                        source_name=src["name"],
                        data=src,
                    ))
        except Exception:
            pass

    async def start(self, hub: Any, check_interval: float = 30.0) -> None:
        """Start the background alert monitoring loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(hub, check_interval))
        log.info("alert_pipeline_started", interval=check_interval)

    async def _loop(self, hub: Any, interval: float) -> None:
        while self._running:
            try:
                await self.check_signals(hub)
            except Exception:
                log.exception("alert_loop_error")
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("alert_pipeline_stopped")

    def get_alerts(
        self,
        limit: int = 50,
        severity: str | None = None,
        alert_type: str | None = None,
        unacknowledged_only: bool = False,
    ) -> list[dict]:
        """Get recent alerts with optional filters."""
        results = []
        for alert in self._alerts:
            if severity and alert.severity.value != severity:
                continue
            if alert_type and alert.alert_type.value != alert_type:
                continue
            if unacknowledged_only and alert.acknowledged:
                continue
            results.append(alert.to_dict())
            if len(results) >= limit:
                break
        return results

    def acknowledge(self, index: int) -> bool:
        """Acknowledge an alert by index."""
        if 0 <= index < len(self._alerts):
            self._alerts[index].acknowledged = True
            return True
        return False

    def acknowledge_all(self) -> int:
        """Acknowledge all alerts. Returns count."""
        count = 0
        for alert in self._alerts:
            if not alert.acknowledged:
                alert.acknowledged = True
                count += 1
        return count

    def stats(self) -> dict:
        total = len(self._alerts)
        unacked = sum(1 for a in self._alerts if not a.acknowledged)
        by_severity = {}
        by_type = {}
        for a in self._alerts:
            by_severity[a.severity.value] = by_severity.get(a.severity.value, 0) + 1
            by_type[a.alert_type.value] = by_type.get(a.alert_type.value, 0) + 1

        return {
            "total_alerts": total,
            "unacknowledged": unacked,
            "by_severity": by_severity,
            "by_type": by_type,
            "running": self._running,
        }
