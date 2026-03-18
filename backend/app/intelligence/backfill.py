"""
Phase 16 — Historical Backfill Engine.

Records all intelligence signals over time for:
  1. Backtesting new strategies against historical alt-data
  2. Training the confidence tracker from historical accuracy
  3. Visualizing signal evolution on the dashboard
  4. Computing feature importance over time

Uses a lightweight in-memory ring buffer + periodic JSON dump.
Can optionally write to the database if available.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.logging_config import get_logger

log = get_logger("intelligence.backfill")

# 24h of signal snapshots at 30s intervals ≈ 2880 entries
DEFAULT_MAX_SNAPSHOTS = 3000


@dataclass
class SignalSnapshot:
    """A point-in-time capture of all source signals."""
    timestamp: float
    signals: dict[str, dict[str, dict[str, Any]]]  # source → ticker → signal_data
    source_health: dict[str, dict[str, Any]]        # source → health_data


class HistoricalBackfillEngine:
    """
    Records intelligence system state over time.

    Periodically snapshots all signals from the DataSourceHub
    and stores them in a ring buffer with optional disk persistence.
    """

    def __init__(
        self,
        max_snapshots: int = DEFAULT_MAX_SNAPSHOTS,
        snapshot_interval: float = 60.0,
        persist_dir: str | None = None,
    ) -> None:
        self._max_snapshots = max_snapshots
        self._snapshot_interval = snapshot_interval
        self._snapshots: deque[SignalSnapshot] = deque(maxlen=max_snapshots)

        # Persistence
        self._persist_dir = Path(persist_dir) if persist_dir else None
        if self._persist_dir:
            self._persist_dir.mkdir(parents=True, exist_ok=True)

        self._running = False
        self._task: asyncio.Task | None = None
        self._stats = {"snapshots_taken": 0, "persists": 0, "errors": 0}

    async def start(self, hub: Any) -> None:
        """Start background snapshot loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(hub))
        log.info("backfill_engine_started", interval=self._snapshot_interval)

    async def _loop(self, hub: Any) -> None:
        while self._running:
            try:
                self._take_snapshot(hub)
            except Exception:
                self._stats["errors"] += 1
                log.exception("backfill_snapshot_error")
            await asyncio.sleep(self._snapshot_interval)

    def _take_snapshot(self, hub: Any) -> None:
        """Take a point-in-time snapshot of all signals."""
        now = time.time()

        # Capture signals
        signals_data: dict[str, dict[str, dict[str, Any]]] = {}
        try:
            all_signals = hub.get_all_signals()
            for source_name, ticker_signals in all_signals.items():
                signals_data[source_name] = {}
                for ticker, signal in ticker_signals.items():
                    signals_data[source_name][ticker] = {
                        "signal_value": signal.signal_value,
                        "confidence": signal.confidence,
                        "edge_estimate": signal.edge_estimate,
                        "category": signal.category,
                        "headline": signal.headline,
                        "features": dict(signal.features) if signal.features else {},
                    }
        except Exception:
            pass

        # Capture health
        health_data: dict[str, dict[str, Any]] = {}
        try:
            status = hub.status()
            for src in status.get("sources", []):
                health_data[src["name"]] = src
        except Exception:
            pass

        snapshot = SignalSnapshot(
            timestamp=now,
            signals=signals_data,
            source_health=health_data,
        )
        self._snapshots.append(snapshot)
        self._stats["snapshots_taken"] += 1

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        # Final persist
        if self._persist_dir:
            self._persist_to_disk()
        log.info("backfill_engine_stopped", snapshots=len(self._snapshots))

    def _persist_to_disk(self) -> None:
        """Write current buffer to a JSON file."""
        if not self._persist_dir:
            return
        try:
            filepath = self._persist_dir / f"backfill_{int(time.time())}.json"
            data = [
                {
                    "timestamp": s.timestamp,
                    "signals": s.signals,
                    "source_health": s.source_health,
                }
                for s in self._snapshots
            ]
            filepath.write_text(json.dumps(data, default=str))
            self._stats["persists"] += 1
            log.info("backfill_persisted", path=str(filepath), snapshots=len(data))
        except Exception:
            log.exception("backfill_persist_error")

    # ── Query API ──

    def get_timeline(
        self,
        source_name: str | None = None,
        category: str | None = None,
        hours: float = 1.0,
        max_points: int = 100,
    ) -> list[dict]:
        """Get a time-series of signal values for charting.

        Returns [{timestamp, sources: {name: avg_signal}}]
        """
        cutoff = time.time() - (hours * 3600)

        # Filter snapshots by time
        relevant = [s for s in self._snapshots if s.timestamp >= cutoff]

        # Downsample if too many points
        if len(relevant) > max_points:
            step = len(relevant) / max_points
            relevant = [relevant[int(i * step)] for i in range(max_points)]

        timeline = []
        for snap in relevant:
            point: dict[str, Any] = {"timestamp": snap.timestamp, "sources": {}}

            for src_name, ticker_signals in snap.signals.items():
                if source_name and src_name != source_name:
                    continue

                # Average signal across tickers (optionally filtered by category)
                values = []
                for ticker, sig_data in ticker_signals.items():
                    if category and sig_data.get("category") != category:
                        continue
                    values.append(sig_data.get("signal_value", 0.0))

                if values:
                    point["sources"][src_name] = round(sum(values) / len(values), 4)

            if point["sources"]:
                timeline.append(point)

        return timeline

    def get_source_accuracy_history(
        self,
        hours: float = 6.0,
    ) -> dict[str, list[dict]]:
        """Get health metrics over time per source for the dashboard."""
        cutoff = time.time() - (hours * 3600)
        result: dict[str, list[dict]] = {}

        for snap in self._snapshots:
            if snap.timestamp < cutoff:
                continue
            for src_name, health in snap.source_health.items():
                if src_name not in result:
                    result[src_name] = []
                result[src_name].append({
                    "timestamp": snap.timestamp,
                    "healthy": health.get("healthy", False),
                    "fetch_count": health.get("fetch_count", 0),
                    "error_count": health.get("error_count", 0),
                    "signal_count": health.get("signal_count", 0),
                    "latency_ms": health.get("avg_latency_ms", 0),
                })

        return result

    def get_latest_snapshot(self) -> dict | None:
        """Get the most recent snapshot."""
        if not self._snapshots:
            return None
        snap = self._snapshots[-1]
        return {
            "timestamp": snap.timestamp,
            "signals": snap.signals,
            "source_health": snap.source_health,
        }

    def stats(self) -> dict:
        return {
            **self._stats,
            "buffer_size": len(self._snapshots),
            "buffer_capacity": self._max_snapshots,
            "oldest": self._snapshots[0].timestamp if self._snapshots else None,
            "newest": self._snapshots[-1].timestamp if self._snapshots else None,
            "running": self._running,
        }
