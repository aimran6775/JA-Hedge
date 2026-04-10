"""
Frankenstein — Market Outcome Harvester. 🧟🌾

Phase 35: The #1 data advantage.

Problem: We only train on markets where we placed trades (~2000).
But Kalshi resolves THOUSANDS of markets daily that we observe but
don't trade. Each resolved market is a free labeled training sample.

Solution: During each scan cycle, snapshot features for ALL candidate
markets (not just traded ones). When markets resolve, match them to
saved features → massive training data increase.

Expected impact: 10-50x more training data → dramatically better
XGBoost generalization, especially for rare categories.

Architecture:
    scan() → harvester.snapshot(candidates, features_list)
                ↓
        _snapshots: {ticker: (features_array, timestamp, category)}
                ↓
    resolve_cycle() → check settlements → create training records
                ↓
        _harvest_buffer: [(X_row, y_label, category, timestamp)]
                ↓
    learner.retrain() → get_harvest_data() → blended with trade data
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.logging_config import get_logger
from app.pipeline import market_cache

log = get_logger("frankenstein.harvester")


@dataclass
class HarvestRecord:
    """A resolved market observation (not necessarily traded)."""
    ticker: str
    features: list[float]
    label: float  # 1.0 = YES, 0.0 = NO
    category: str
    timestamp: float
    market_price_at_snapshot: float  # what the market priced it at
    source: str = "harvest"  # always "harvest"


class MarketHarvester:
    """
    Collects free training data from ALL observed markets.

    Usage:
        1. Scanner calls snapshot() each scan with all candidates
        2. Brain's resolver calls try_harvest() after settlements
        3. Learner calls get_training_data() to blend with trade data
    """

    def __init__(
        self,
        max_snapshots: int = 20_000,
        max_harvest: int = 50_000,
        snapshot_ttl_hours: float = 72.0,
    ) -> None:
        # Pending snapshots: {ticker: (features_list, timestamp, category, market_price)}
        # Only keep the MOST RECENT snapshot per ticker (overwrite on rescan)
        self._snapshots: dict[str, tuple[list[float], float, str, float]] = {}
        self._max_snapshots = max_snapshots
        self._snapshot_ttl = snapshot_ttl_hours * 3600

        # Resolved harvest records (ring buffer)
        self._harvest: deque[HarvestRecord] = deque(maxlen=max_harvest)

        # Stats
        self._total_snapshots = 0
        self._total_harvested = 0
        self._total_expired = 0

    def snapshot(
        self,
        candidates: list[Any],
        features_list: list[MarketFeatures],
    ) -> int:
        """Save feature snapshots for all scan candidates.

        Called by scanner each cycle. Overwrites previous snapshot
        for the same ticker (we want the LATEST features before resolution).

        Returns number of snapshots saved.
        """
        now = time.time()
        saved = 0

        for market, feat in zip(candidates, features_list):
            ticker = market.ticker
            if not feat or float(feat.midpoint) <= 0:
                continue

            # Detect category from features (already computed by FeatureEngine)
            cat = ""
            _cat_id = int(feat.category_id)
            _id_to_cat = {
                1: "politics", 2: "economics", 3: "finance", 4: "crypto",
                5: "sports", 6: "entertainment", 7: "science", 8: "weather",
                9: "social_media", 10: "tech", 11: "health", 12: "legal",
            }
            cat = _id_to_cat.get(_cat_id, getattr(market, "category", "") or "unknown")

            self._snapshots[ticker] = (
                feat.to_array().tolist(),
                now,
                cat,
                float(feat.midpoint),
            )
            saved += 1

        self._total_snapshots += saved

        # Evict old snapshots if over limit
        if len(self._snapshots) > self._max_snapshots:
            self._evict_old()

        return saved

    def try_harvest(
        self,
        settled_tickers: dict[str, str],
    ) -> int:
        """Convert settled markets into training records.

        Args:
            settled_tickers: {ticker: "yes" | "no"} — recently settled markets

        Returns number of new training records created.
        """
        now = time.time()
        harvested = 0

        for ticker, result in settled_tickers.items():
            if result not in ("yes", "no"):
                continue

            snap = self._snapshots.pop(ticker, None)
            if snap is None:
                continue

            features_list, snap_ts, category, market_price = snap

            # Skip if snapshot is too old (features may be stale)
            if (now - snap_ts) > self._snapshot_ttl:
                self._total_expired += 1
                continue

            label = 1.0 if result == "yes" else 0.0

            record = HarvestRecord(
                ticker=ticker,
                features=features_list,
                label=label,
                category=category,
                timestamp=snap_ts,
                market_price_at_snapshot=market_price,
            )
            self._harvest.append(record)
            harvested += 1

        self._total_harvested += harvested

        if harvested > 0:
            log.info(
                "🌾 markets_harvested",
                new=harvested,
                total_buffer=len(self._harvest),
                pending_snapshots=len(self._snapshots),
            )

        return harvested

    def get_training_data(
        self,
        max_samples: int = 0,
        max_age_hours: float = 0,
        category_filter: str = "",
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
        """Extract training data from harvest buffer.

        Returns (X, y, sample_weights) or None if insufficient data.
        Weights are lower than traded data (0.5) since we don't know
        our own prediction quality for these markets.
        """
        if not self._harvest:
            return None

        now = time.time()
        expected_dim = len(MarketFeatures.feature_names())

        records = []
        for r in self._harvest:
            if max_age_hours > 0 and (now - r.timestamp) > max_age_hours * 3600:
                continue
            if category_filter and r.category != category_filter:
                continue
            records.append(r)

        if max_samples > 0 and len(records) > max_samples:
            # Keep most recent
            records = records[-max_samples:]

        if len(records) < 20:
            return None

        # Build arrays with dimension padding
        padded = []
        for r in records:
            feat = list(r.features)
            if len(feat) < expected_dim:
                feat.extend([0.0] * (expected_dim - len(feat)))
            elif len(feat) > expected_dim:
                feat = feat[:expected_dim]
            padded.append(feat)

        X = np.array(padded, dtype=np.float32)
        y = np.array([r.label for r in records], dtype=np.float32)

        # Weights: harvest data gets 0.5 weight (vs 1.0 for traded data)
        # More recent harvest is weighted higher
        weights = np.ones(len(records), dtype=np.float32) * 0.5
        for i, r in enumerate(records):
            age_hours = (now - r.timestamp) / 3600.0
            recency = np.exp(-age_hours / 48.0)  # half-life 48h
            weights[i] *= max(recency, 0.2)

        return X, y, weights

    def _evict_old(self) -> None:
        """Remove oldest snapshots to stay under limit."""
        now = time.time()
        expired = [
            t for t, (_, ts, _, _) in self._snapshots.items()
            if (now - ts) > self._snapshot_ttl
        ]
        for t in expired:
            del self._snapshots[t]
            self._total_expired += 1

        # If still over, remove oldest by timestamp
        if len(self._snapshots) > self._max_snapshots:
            sorted_tickers = sorted(
                self._snapshots.items(), key=lambda x: x[1][1]
            )
            remove_count = len(self._snapshots) - self._max_snapshots + 1000
            for ticker, _ in sorted_tickers[:remove_count]:
                del self._snapshots[ticker]

    def stats(self) -> dict[str, Any]:
        """Harvester statistics."""
        harvest_labels = [r.label for r in self._harvest] if self._harvest else []
        return {
            "pending_snapshots": len(self._snapshots),
            "harvest_buffer": len(self._harvest),
            "total_snapshots": self._total_snapshots,
            "total_harvested": self._total_harvested,
            "total_expired": self._total_expired,
            "harvest_positive_rate": (
                f"{sum(harvest_labels) / len(harvest_labels):.3f}"
                if harvest_labels else "n/a"
            ),
            "categories": dict(
                sorted(
                    {
                        cat: sum(1 for r in self._harvest if r.category == cat)
                        for cat in set(r.category for r in self._harvest)
                    }.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )
            ) if self._harvest else {},
        }
