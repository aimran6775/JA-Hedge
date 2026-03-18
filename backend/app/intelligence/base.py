"""
Base classes for all data source adapters.

Every data source (sports odds, news, Twitter, weather, crypto, etc.)
implements the DataSource interface.  The DataSourceHub manages their
lifecycle, polls them, and merges their signals into the feature vector.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DataSourceType(str, Enum):
    """Categories of data sources."""
    SPORTS_ODDS = "sports_odds"
    NEWS = "news"
    SOCIAL = "social"
    WEATHER = "weather"
    CRYPTO = "crypto"
    PREDICTION_MARKET = "prediction_market"
    ECONOMIC = "economic"
    POLITICAL = "political"
    TRENDS = "trends"
    CUSTOM = "custom"


@dataclass
class SourceSignal:
    """A single signal emitted by a data source.

    Signals are ticker-level: one source can emit many signals per scan
    (one for each relevant Kalshi market it has data on).
    """
    source_name: str
    source_type: DataSourceType
    ticker: str                       # Kalshi ticker this signal applies to
    timestamp: float = 0.0            # Unix epoch

    # Core signal data
    signal_value: float = 0.0         # Normalised −1.0 (strong NO) to +1.0 (strong YES)
    confidence: float = 0.0           # 0.0–1.0, how confident the source is
    edge_estimate: float = 0.0        # Source's estimate of mispricing (signed)

    # Optional rich fields
    category: str = ""                # e.g. "politics", "weather", "nba"
    headline: str = ""                # Human-readable reason
    raw_data: dict[str, Any] = field(default_factory=dict)

    # Feature injection — extra features to merge into the ML feature vector
    features: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class SourceHealth:
    """Health/status snapshot for a single data source."""
    name: str
    source_type: DataSourceType
    enabled: bool = True
    healthy: bool = True
    last_fetch_time: float = 0.0
    last_success_time: float = 0.0
    last_error: str | None = None
    total_fetches: int = 0
    total_errors: int = 0
    total_signals: int = 0
    avg_latency_ms: float = 0.0
    signals_per_minute: float = 0.0
    uptime_pct: float = 100.0

    # Cost tracking
    api_calls_used: int = 0
    api_calls_limit: int = 0          # 0 = unlimited
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.source_type.value,
            "enabled": self.enabled,
            "healthy": self.healthy,
            "last_fetch_time": self.last_fetch_time,
            "last_success_time": self.last_success_time,
            "last_error": self.last_error,
            "fetch_count": self.total_fetches,
            "error_count": self.total_errors,
            "signal_count": self.total_signals,
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "signals_per_minute": round(self.signals_per_minute, 2),
            "uptime_pct": round(self.uptime_pct, 1),
            "api_calls_used": self.api_calls_used,
            "api_calls_limit": self.api_calls_limit,
            "cost_usd": round(self.cost_usd, 4),
        }


class DataSource(ABC):
    """Abstract base class for all data source adapters.

    Lifecycle:
      1. __init__() — configure (API keys, URLs, etc.)
      2. start() — open connections, start background tasks
      3. fetch_signals() — called periodically by the Hub
      4. stop() — clean up connections
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique human-readable name (e.g. 'draftkings_odds')."""
        ...

    @property
    @abstractmethod
    def source_type(self) -> DataSourceType:
        """Category of this source."""
        ...

    @property
    def enabled(self) -> bool:
        """Whether this source is active. Override to read from config."""
        return True

    @property
    def poll_interval_seconds(self) -> float:
        """How often the Hub should call fetch_signals(). Default 60s."""
        return 60.0

    @abstractmethod
    async def start(self) -> None:
        """Initialise the source (open connections, warm caches)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Tear down gracefully."""
        ...

    @abstractmethod
    async def fetch_signals(self, tickers: list[str] | None = None) -> list[SourceSignal]:
        """Fetch current signals.

        Args:
            tickers: Optional filter — only return signals for these
                     Kalshi tickers.  None = return all available.

        Returns:
            List of SourceSignal, one per relevant market.
        """
        ...

    def health(self) -> SourceHealth:
        """Return current health status.  Override for richer data."""
        return SourceHealth(
            name=self.name,
            source_type=self.source_type,
            enabled=self.enabled,
        )
