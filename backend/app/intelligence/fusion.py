"""
Phase 9 — Feature Fusion Engine.

Merges alternative data signals from all DataSource adapters into
the existing 57-feature vector used by the XGBoost model.

Approach:
  • Base features (57) remain untouched — they are the foundation
  • Alt-data features are appended as a separate block
  • Features are normalised and missing values filled with 0.0
  • The model sees a flat vector: [base_57 | alt_N]
  • When a source is down, its features are all 0.0 (graceful degradation)

Phase 14 (Adaptive Source Weighting) builds on top of this by
learning per-source weights from historical accuracy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.logging_config import get_logger

log = get_logger("intelligence.fusion")


# All possible alt-data feature names in canonical order.
# New sources register their features here so the model vector
# has a stable, predictable shape.
ALT_DATA_FEATURES = [
    # Sports odds (Phase 2)
    "sports_odds_scraper_signal",
    "sports_odds_scraper_confidence",
    "sports_odds_scraper_edge",
    "sports_odds_scraper_vegas_home_prob",
    "sports_odds_scraper_vegas_away_prob",
    "sports_odds_scraper_num_books",
    "sports_odds_scraper_book_spread",
    # News sentiment (Phase 3)
    "news_sentiment_signal",
    "news_sentiment_confidence",
    "news_sentiment_edge",
    "news_sentiment_news_sentiment",
    "news_sentiment_news_volume",
    "news_sentiment_news_positive_ratio",
    "news_sentiment_news_negative_ratio",
    # Social / Twitter (Phase 4)
    "social_twitter_signal",
    "social_twitter_confidence",
    "social_twitter_edge",
    "social_twitter_social_sentiment",
    "social_twitter_social_volume",
    "social_twitter_social_max_engagement",
    "social_twitter_social_positive_ratio",
    # Weather (Phase 5)
    "weather_feed_signal",
    "weather_feed_confidence",
    "weather_feed_temp_f",
    "weather_feed_humidity",
    "weather_feed_wind_mph",
    "weather_feed_extreme_score",
    "weather_feed_alert_severity",
    # Crypto (Phase 6)
    "crypto_prices_signal",
    "crypto_prices_confidence",
    "crypto_prices_crypto_change_1h",
    "crypto_prices_crypto_change_24h",
    "crypto_prices_crypto_volatility",
    "crypto_prices_crypto_momentum",
    "crypto_prices_crypto_range_position",
    # Polymarket (Phase 7)
    "polymarket_signal",
    "polymarket_confidence",
    "polymarket_edge",
    "polymarket_poly_price",
    "polymarket_poly_volume_24h",
    "polymarket_poly_spread",
    # Economic (Phase 8)
    "economic_fred_signal",
    "economic_fred_confidence",
    "economic_fred_edge",
    # Political (Phase 11)
    "political_congress_signal",
    "political_congress_confidence",
    "political_congress_bill_progress",
    # Google Trends (Phase 12)
    "google_trends_signal",
    "google_trends_confidence",
    "google_trends_trend_traffic",
    "google_trends_trend_sentiment",
    # Source meta-features (Phase 13)
    "source_count",
    "source_agreement",
    "source_avg_confidence",
    "source_max_edge",
    "source_signal_age_min",
]


@dataclass
class FusedFeatures:
    """Combined base + alt-data feature set for a single market."""
    ticker: str
    base_features: Any = None  # MarketFeatures from app.ai.features
    alt_features: dict[str, float] = field(default_factory=dict)
    source_count: int = 0
    timestamp: float = 0.0

    def to_full_vector(self) -> list[float]:
        """Produce the complete feature vector: base_57 + alt_N."""
        base = []
        if self.base_features and hasattr(self.base_features, "to_array"):
            base = list(self.base_features.to_array())

        alt = [self.alt_features.get(name, 0.0) for name in ALT_DATA_FEATURES]
        return base + alt

    @property
    def alt_feature_count(self) -> int:
        return len(ALT_DATA_FEATURES)


class FeatureFusionEngine:
    """
    Merges signals from DataSourceHub into the ML feature vector.

    Called by Frankenstein before each prediction to enrich the base
    57-feature vector with alt-data features.
    """

    def __init__(self, hub: Any = None) -> None:
        """
        Args:
            hub: DataSourceHub instance (injected at startup).
        """
        self._hub = hub
        self._fusion_cache: dict[str, FusedFeatures] = {}
        self._stats = {
            "fusions": 0,
            "cache_hits": 0,
            "sources_merged": 0,
        }
        self._cache_ttl = 30.0  # seconds

    def set_hub(self, hub: Any) -> None:
        self._hub = hub

    def fuse(self, ticker: str, base_features: Any = None) -> FusedFeatures:
        """
        Produce a FusedFeatures for a ticker, merging base + all alt-data.

        Args:
            ticker: Kalshi market ticker
            base_features: MarketFeatures from FeatureEngine.compute()

        Returns:
            FusedFeatures with both base and alt-data features populated.
        """
        now = time.time()

        # Check cache
        cached = self._fusion_cache.get(ticker)
        if cached and (now - cached.timestamp) < self._cache_ttl:
            # Refresh base features but keep alt-data from cache
            if base_features:
                cached.base_features = base_features
            self._stats["cache_hits"] += 1
            return cached

        # Build alt-data features from hub
        alt_features: dict[str, float] = {}
        source_count = 0

        if self._hub:
            raw = self._hub.get_features_for_ticker(ticker)
            alt_features.update(raw)
            source_count = self._hub.get_source_count(ticker)

            # Also check category-level signals (e.g., "news:politics")
            # The hub stores signals by ticker, and category signals use
            # synthetic tickers like "news:politics", "social:crypto", etc.
            # We match those to the market's category.
            if base_features and hasattr(base_features, "category"):
                cat = getattr(base_features, "category", "")
                if cat:
                    for prefix in ["news:", "social:", "trends:"]:
                        cat_raw = self._hub.get_features_for_ticker(f"{prefix}{cat}")
                        alt_features.update(cat_raw)
                        if cat_raw:
                            source_count += 1

        # Add meta-features (Phase 13)
        alt_features["source_count"] = float(source_count)
        if source_count > 0 and self._hub:
            signals = self._hub.get_signals_for_ticker(ticker)
            if signals:
                alt_features["source_agreement"] = self._compute_agreement(signals)
                alt_features["source_avg_confidence"] = sum(s.confidence for s in signals) / len(signals)
                alt_features["source_max_edge"] = max(abs(s.edge_estimate) for s in signals)
                alt_features["source_signal_age_min"] = min(
                    (now - s.timestamp) / 60 for s in signals
                )

        fused = FusedFeatures(
            ticker=ticker,
            base_features=base_features,
            alt_features=alt_features,
            source_count=source_count,
            timestamp=now,
        )

        self._fusion_cache[ticker] = fused
        self._stats["fusions"] += 1
        self._stats["sources_merged"] += source_count

        return fused

    @staticmethod
    def _compute_agreement(signals: list) -> float:
        """Compute how much sources agree on direction.

        Returns 0.0 (total disagreement) to 1.0 (all same direction).
        """
        if not signals:
            return 0.0

        positive = sum(1 for s in signals if s.signal_value > 0)
        negative = sum(1 for s in signals if s.signal_value < 0)
        total = positive + negative

        if total == 0:
            return 0.5  # neutral

        majority = max(positive, negative)
        return majority / total

    def get_alt_feature_names(self) -> list[str]:
        """Get the canonical list of alt-data feature names."""
        return list(ALT_DATA_FEATURES)

    def stats(self) -> dict:
        return dict(self._stats)

    def clear_cache(self) -> None:
        self._fusion_cache.clear()
