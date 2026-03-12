"""
JA Hedge — Category-Specific Trading Strategies (Phase 8).

Different market categories require different approaches:

  Sports:      Compare to Vegas/offshore odds for edge detection
  Economics:   FRED data, consensus estimates, nowcasting
  Weather:     NWS forecasts, historical climate data
  Politics:    Polling aggregation, prediction market consensus
  Crypto:      On-chain metrics, sentiment indicators
  General:     Fallback to base ML model

Each category strategy provides:
  1. Category detection from market metadata
  2. External signal integration
  3. Confidence adjustment based on domain knowledge
  4. Category-specific feature computation
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.ai.features import MarketFeatures
from app.ai.models import Prediction
from app.logging_config import get_logger

log = get_logger("frankenstein.categories")


@dataclass
class CategorySignal:
    """External signal from a category-specific source."""
    source: str             # e.g., "vegas_odds", "nws_forecast", "fred_data"
    direction: str          # "yes" or "no"
    strength: float         # 0.0 to 1.0
    confidence: float       # how much we trust this source
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class CategoryAdjustment:
    """Adjustment to model prediction based on category knowledge."""
    category: str
    adjustment: float       # additive adjustment to predicted prob
    confidence_boost: float # multiplicative boost to confidence
    signals: list[CategorySignal] = field(default_factory=list)
    reason: str = ""


# ── Category Detection ────────────────────────────────────────────────────


CATEGORY_KEYWORDS = {
    "sports": [
        "nfl", "nba", "mlb", "nhl", "mls", "ncaa", "football", "basketball",
        "baseball", "hockey", "soccer", "tennis", "golf", "boxing", "ufc",
        "mma", "super bowl", "world series", "playoffs", "championship",
        "game", "match", "score", "points", "touchdown", "home run",
        "win", "loss", "spread", "over/under", "moneyline",
    ],
    "economics": [
        "gdp", "cpi", "inflation", "unemployment", "fed", "fomc",
        "interest rate", "jobs", "payroll", "retail sales", "housing",
        "treasury", "yield", "recession", "pce", "consumer",
        "manufacturing", "ism", "pmi", "trade balance", "deficit",
    ],
    "weather": [
        "temperature", "hurricane", "storm", "rain", "snow", "weather",
        "tornado", "flood", "heat", "cold", "celsius", "fahrenheit",
        "wind", "precipitation", "forecast", "noaa", "nws", "climate",
    ],
    "politics": [
        "election", "vote", "poll", "president", "congress", "senate",
        "house", "governor", "democrat", "republican", "party",
        "approval", "impeach", "legislation", "bill", "law",
        "cabinet", "supreme court", "primary", "caucus",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain",
        "defi", "token", "coin", "mining", "wallet", "exchange",
    ],
    "entertainment": [
        "oscars", "grammy", "emmy", "golden globe", "box office",
        "movie", "film", "tv", "show", "album", "chart", "billboard",
        "streaming", "netflix", "spotify", "award",
    ],
}


def detect_category(title: str, category_hint: str = "") -> str:
    """Detect market category from title and metadata."""
    if category_hint:
        # Some markets already have a category from Kalshi
        hint_lower = category_hint.lower()
        for cat in CATEGORY_KEYWORDS:
            if cat in hint_lower:
                return cat

    title_lower = title.lower() if title else ""

    # Score each category by keyword matches
    scores: dict[str, int] = {}
    for cat, keywords in CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in title_lower)
        if score > 0:
            scores[cat] = score

    if scores:
        return max(scores, key=scores.get)

    return "general"


# ── Base Category Strategy ────────────────────────────────────────────────


class CategoryStrategy(ABC):
    """Base class for category-specific trading strategies."""

    @property
    @abstractmethod
    def category(self) -> str:
        ...

    @abstractmethod
    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        """Adjust a model prediction using category-specific knowledge."""
        ...

    def get_external_signals(self, market_title: str, ticker: str = "") -> list[CategorySignal]:
        """Fetch external signals (override for API integrations)."""
        return []


# ── Sports Strategy ──────────────────────────────────────────────────────


class SportsStrategy(CategoryStrategy):
    """
    Sports market strategy.

    Key insight: Sports markets converge to fair odds much faster
    than other categories because of deep liquidity from sharp bettors.

    Approach:
    - Trust high-volume sports market prices more
    - Look for edge only in low-volume / niche markets
    - Adjust for time-of-game effects (live markets move fast)
    - Compare to consensus lines when available
    """

    @property
    def category(self) -> str:
        return "sports"

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        adjustment = 0.0
        confidence_boost = 1.0
        reason_parts = []

        # Sports markets with high volume are very efficient
        # → reduce our edge estimates (be more humble)
        if features.volume > 1000:
            confidence_boost *= 0.85
            reason_parts.append("high_vol_efficient")

        # Near-game markets are ultra-efficient
        if features.hours_to_expiry < 2:
            confidence_boost *= 0.70
            reason_parts.append("near_game_efficient")

        # Wide spread in sports = possible mispricing opportunity
        if features.spread_pct > 0.08:
            confidence_boost *= 1.15
            reason_parts.append("wide_spread_opportunity")

        return CategoryAdjustment(
            category="sports",
            adjustment=adjustment,
            confidence_boost=confidence_boost,
            reason="; ".join(reason_parts),
        )


# ── Economics Strategy ───────────────────────────────────────────────────


class EconomicsStrategy(CategoryStrategy):
    """
    Economics/macro market strategy.

    Key insight: Economic data markets have scheduled release times.
    Before release: market is uncertain, prices near 50%.
    After release: market snaps to true value instantly.

    Approach:
    - Avoid trading into releases (high binary risk)
    - After releases, capture any delayed market reaction
    - Use consensus estimates as anchor
    - Monitor FRED data for leading indicators
    """

    @property
    def category(self) -> str:
        return "economics"

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        adjustment = 0.0
        confidence_boost = 1.0
        reason_parts = []

        # Econ markets near 50% with short expiry = data release pending
        # Very risky — reduce confidence dramatically
        if features.hours_to_expiry < 6 and features.prob_distance_from_50 < 0.15:
            confidence_boost *= 0.40
            reason_parts.append("pending_data_release_risk")

        # After data release (price moved sharply + near expiry)
        if features.hours_to_expiry < 2 and features.prob_distance_from_50 > 0.35:
            confidence_boost *= 1.20
            reason_parts.append("post_release_convergence")

        # Very low volume econ markets may have stale prices
        if features.volume < 50:
            confidence_boost *= 0.90
            reason_parts.append("low_vol_stale_risk")

        return CategoryAdjustment(
            category="economics",
            adjustment=adjustment,
            confidence_boost=confidence_boost,
            reason="; ".join(reason_parts),
        )


# ── Weather Strategy ─────────────────────────────────────────────────────


class WeatherStrategy(CategoryStrategy):
    """
    Weather market strategy.

    Key insight: Weather forecasts improve dramatically as the
    target date approaches. NWS 7-day forecasts are ~80% accurate,
    but 1-day forecasts are ~95%+ accurate.

    Approach:
    - Trust market prices more for distant weather events
    - Near event date, compare to latest NWS forecast
    - Historical climate data provides a strong prior
    """

    @property
    def category(self) -> str:
        return "weather"

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        adjustment = 0.0
        confidence_boost = 1.0
        reason_parts = []

        # Weather events far out — uncertain, trust market
        if features.hours_to_expiry > 168:  # >1 week
            confidence_boost *= 0.70
            reason_parts.append("distant_weather_uncertain")

        # Weather events imminent — forecasts very accurate
        if features.hours_to_expiry < 24:
            confidence_boost *= 1.15
            reason_parts.append("imminent_weather_accurate")

        # Extreme weather events (hurricanes etc.) — high volatility
        title_lower = (market_title or "").lower()
        if any(w in title_lower for w in ["hurricane", "tornado", "blizzard"]):
            confidence_boost *= 0.80
            reason_parts.append("extreme_weather_volatile")

        return CategoryAdjustment(
            category="weather",
            adjustment=adjustment,
            confidence_boost=confidence_boost,
            reason="; ".join(reason_parts),
        )


# ── Politics Strategy ────────────────────────────────────────────────────


class PoliticsStrategy(CategoryStrategy):
    """
    Politics market strategy.

    Key insight: Political markets are often influenced by
    narrative/sentiment more than fundamentals. Polling aggregation
    provides the strongest signal.

    Approach:
    - Compare to polling averages where available
    - Far-out elections: wide range, low confidence
    - Near election: high-information, trust market more
    - Watch for narrative shifts (large volume spikes)
    """

    @property
    def category(self) -> str:
        return "politics"

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        adjustment = 0.0
        confidence_boost = 1.0
        reason_parts = []

        # Political markets far from election — very uncertain
        if features.hours_to_expiry > 720:  # >30 days
            confidence_boost *= 0.65
            reason_parts.append("far_from_event")

        # Volume surge in political market = narrative shift
        if features.volume_ratio > 3.0:
            confidence_boost *= 0.85
            reason_parts.append("narrative_shift_volatile")

        return CategoryAdjustment(
            category="politics",
            adjustment=adjustment,
            confidence_boost=confidence_boost,
            reason="; ".join(reason_parts),
        )


# ── General Fallback ─────────────────────────────────────────────────────


class GeneralStrategy(CategoryStrategy):
    """Fallback strategy — no category-specific adjustments."""

    @property
    def category(self) -> str:
        return "general"

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        return CategoryAdjustment(
            category="general",
            adjustment=0.0,
            confidence_boost=1.0,
        )


# ── Strategy Registry ────────────────────────────────────────────────────


class CategoryStrategyRegistry:
    """
    Registry of all category strategies.
    Used by Frankenstein to apply the right strategy per market.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, CategoryStrategy] = {}
        self._default = GeneralStrategy()

        # Register built-in strategies
        for cls in [SportsStrategy, EconomicsStrategy, WeatherStrategy, PoliticsStrategy]:
            s = cls()
            self._strategies[s.category] = s

    def get(self, category: str) -> CategoryStrategy:
        """Get strategy for a category."""
        return self._strategies.get(category, self._default)

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
        category_hint: str = "",
    ) -> tuple[Prediction, CategoryAdjustment]:
        """
        Apply category-specific adjustments to a prediction.

        Returns (adjusted_prediction, adjustment_details).
        """
        category = detect_category(market_title, category_hint)
        strategy = self.get(category)
        adj = strategy.adjust_prediction(prediction, features, market_title)

        # Apply adjustment
        new_prob = max(0.01, min(0.99, prediction.predicted_prob + adj.adjustment))
        new_confidence = max(0.01, min(0.99, prediction.confidence * adj.confidence_boost))

        # Rebuild prediction with adjusted values
        adjusted = Prediction(
            side=prediction.side,
            confidence=new_confidence,
            predicted_prob=new_prob,
            edge=prediction.edge,  # edge stays the same (it's vs market price)
            model_name=prediction.model_name,
            model_version=prediction.model_version,
        )

        return adjusted, adj

    def stats(self) -> dict[str, Any]:
        return {
            "registered_categories": list(self._strategies.keys()),
            "default": self._default.category,
        }
