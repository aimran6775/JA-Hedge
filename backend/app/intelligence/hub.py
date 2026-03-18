"""
DataSourceHub — Central registry and orchestrator for all data sources.

Responsibilities:
  • Register / deregister DataSource adapters
  • Poll each source on its own interval in background tasks
  • Maintain a signal cache (latest signal per source × ticker)
  • Expose health snapshots for the dashboard
  • Provide merged feature dicts for FeatureFusion
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from app.intelligence.base import (
    DataSource,
    DataSourceType,
    SourceHealth,
    SourceSignal,
)
from app.logging_config import get_logger

log = get_logger("intelligence.hub")


@dataclass
class DataSourceStatus:
    """Aggregate status across all registered sources."""
    total_sources: int = 0
    healthy_sources: int = 0
    total_signals_lifetime: int = 0
    total_errors_lifetime: int = 0
    signals_last_5min: int = 0
    sources: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_sources": self.total_sources,
            "healthy_sources": self.healthy_sources,
            "total_signals_lifetime": self.total_signals_lifetime,
            "total_errors_lifetime": self.total_errors_lifetime,
            "signals_last_5min": self.signals_last_5min,
            "sources": self.sources,
        }


class DataSourceHub:
    """Central registry and background poller for all data sources."""

    def __init__(self) -> None:
        self._sources: dict[str, DataSource] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

        # Signal cache: source_name → ticker → latest SourceSignal
        self._signal_cache: dict[str, dict[str, SourceSignal]] = defaultdict(dict)

        # Health trackers
        self._health: dict[str, SourceHealth] = {}
        self._fetch_times: dict[str, list[float]] = defaultdict(list)  # rolling latencies
        self._signal_timestamps: list[float] = []  # rolling for rate calc

        # Lifetime counters
        self._total_signals = 0
        self._total_errors = 0

        log.info("DataSourceHub created")

    # ── Registration ──────────────────────────────────────────────────

    def register(self, source: DataSource) -> None:
        """Register a data source adapter."""
        name = source.name
        if name in self._sources:
            log.warning("source_already_registered", name=name)
            return

        self._sources[name] = source
        self._health[name] = SourceHealth(
            name=name,
            source_type=source.source_type,
            enabled=source.enabled,
        )
        log.info("source_registered", name=name, type=source.source_type.value,
                 poll_interval=source.poll_interval_seconds)

        # If hub is already running, start this source immediately
        if self._running:
            asyncio.create_task(self._start_source(name))

    def deregister(self, name: str) -> None:
        """Remove a data source."""
        if name in self._tasks:
            self._tasks[name].cancel()
            del self._tasks[name]
        self._sources.pop(name, None)
        self._health.pop(name, None)
        self._signal_cache.pop(name, None)
        log.info("source_deregistered", name=name)

    # ── Lifecycle ─────────────────────────────────────────────────────

    async def start_all(self) -> None:
        """Start all registered sources and begin polling."""
        self._running = True
        for name in list(self._sources):
            await self._start_source(name)
        log.info("hub_started", sources=len(self._sources))

    async def _start_source(self, name: str) -> None:
        """Start a single source + its poll loop."""
        source = self._sources.get(name)
        if not source or not source.enabled:
            return

        try:
            await source.start()
            self._health[name].healthy = True
            log.info("source_started", name=name)
        except Exception as e:
            self._health[name].healthy = False
            self._health[name].last_error = str(e)
            log.error("source_start_failed", name=name, error=str(e))

        # Start background poll task
        task = asyncio.create_task(self._poll_loop(name), name=f"poll_{name}")
        self._tasks[name] = task

    async def stop_all(self) -> None:
        """Stop all sources and cancel poll loops."""
        self._running = False
        for name, task in self._tasks.items():
            task.cancel()
        self._tasks.clear()

        for name, source in self._sources.items():
            try:
                await source.stop()
            except Exception as e:
                log.error("source_stop_error", name=name, error=str(e))

        log.info("hub_stopped")

    # ── Polling ───────────────────────────────────────────────────────

    async def _poll_loop(self, name: str) -> None:
        """Background poll loop for a single source."""
        source = self._sources.get(name)
        if not source:
            return

        while self._running:
            try:
                await self._fetch_one(name, source)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._record_error(name, str(e))
                log.error("poll_error", name=name, error=str(e))

            await asyncio.sleep(source.poll_interval_seconds)

    async def _fetch_one(self, name: str, source: DataSource) -> None:
        """Execute a single fetch cycle for a source."""
        health = self._health[name]
        health.total_fetches += 1
        health.last_fetch_time = time.time()

        t0 = time.monotonic()
        signals = await source.fetch_signals()
        latency_ms = (time.monotonic() - t0) * 1000

        # Track latency (rolling window of 100)
        self._fetch_times[name].append(latency_ms)
        if len(self._fetch_times[name]) > 100:
            self._fetch_times[name] = self._fetch_times[name][-100:]
        health.avg_latency_ms = sum(self._fetch_times[name]) / len(self._fetch_times[name])

        # Update signal cache
        now = time.time()
        for sig in signals:
            self._signal_cache[name][sig.ticker] = sig
            self._signal_timestamps.append(now)

        # Trim rolling timestamp list (keep last 10 minutes)
        cutoff = now - 600
        self._signal_timestamps = [t for t in self._signal_timestamps if t > cutoff]

        health.last_success_time = now
        health.healthy = True
        health.total_signals += len(signals)
        self._total_signals += len(signals)

        # Update source-specific health
        try:
            src_health = source.health()
            health.api_calls_used = src_health.api_calls_used
            health.api_calls_limit = src_health.api_calls_limit
            health.cost_usd = src_health.cost_usd
        except Exception:
            pass

        if signals:
            log.debug("source_fetched", name=name, signals=len(signals),
                      latency_ms=round(latency_ms, 1))

    def _record_error(self, name: str, error: str) -> None:
        health = self._health.get(name)
        if health:
            health.total_errors += 1
            health.last_error = error
            health.healthy = False
        self._total_errors += 1

    # ── Signal Access ─────────────────────────────────────────────────

    def get_signals_for_ticker(self, ticker: str) -> list[SourceSignal]:
        """Get the latest signal from each source for a given ticker."""
        signals = []
        for source_name, ticker_map in self._signal_cache.items():
            sig = ticker_map.get(ticker)
            if sig:
                signals.append(sig)
        return signals

    def get_all_signals(self) -> dict[str, dict[str, SourceSignal]]:
        """Get all cached signals: source_name → ticker → SourceSignal."""
        return dict(self._signal_cache)

    def get_features_for_ticker(self, ticker: str) -> dict[str, float]:
        """Get merged alt-data features for a ticker.

        Returns a flat dict of feature_name → value that can be
        appended to the base 57-feature vector.
        """
        merged: dict[str, float] = {}
        for sig in self.get_signals_for_ticker(ticker):
            # Prefix each source's features to avoid collisions
            prefix = sig.source_name
            merged[f"{prefix}_signal"] = sig.signal_value
            merged[f"{prefix}_confidence"] = sig.confidence
            merged[f"{prefix}_edge"] = sig.edge_estimate
            for k, v in sig.features.items():
                merged[f"{prefix}_{k}"] = v
        return merged

    def get_source_count(self, ticker: str) -> int:
        """How many sources have data for this ticker."""
        count = 0
        for ticker_map in self._signal_cache.values():
            if ticker in ticker_map:
                count += 1
        return count

    # ── Health / Dashboard ────────────────────────────────────────────

    def status(self) -> DataSourceStatus:
        """Aggregate health status for the dashboard."""
        now = time.time()
        five_min_ago = now - 300

        recent_signals = sum(1 for t in self._signal_timestamps if t > five_min_ago)

        sources_list = []
        healthy_count = 0
        for name, health in self._health.items():
            # Compute uptime percentage
            if health.total_fetches > 0:
                health.uptime_pct = (1.0 - health.total_errors / health.total_fetches) * 100
            # Compute signal rate
            if health.last_success_time > 0:
                age = now - health.last_success_time
                if age < 300:
                    health.signals_per_minute = health.total_signals / max(1, (now - health.last_fetch_time)) * 60
            sources_list.append(health.to_dict())
            if health.healthy:
                healthy_count += 1

        return DataSourceStatus(
            total_sources=len(self._sources),
            healthy_sources=healthy_count,
            total_signals_lifetime=self._total_signals,
            total_errors_lifetime=self._total_errors,
            signals_last_5min=recent_signals,
            sources=sources_list,
        )

    def source_names(self) -> list[str]:
        return list(self._sources.keys())

    def is_registered(self, name: str) -> bool:
        return name in self._sources
