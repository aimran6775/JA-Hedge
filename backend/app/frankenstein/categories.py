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
        "world baseball classic", "wbc", "march madness", "champions league",
        "ucl", "premier league", "serie a", "la liga", "bundesliga",
        "rebounds", "assists", "strikeouts", "goals", "saves",
    ],
    "economics": [
        "gdp", "cpi", "inflation", "unemployment", "fed", "fomc",
        "interest rate", "jobs", "payroll", "retail sales", "housing",
        "treasury", "yield", "recession", "pce", "consumer",
        "manufacturing", "ism", "pmi", "trade balance", "deficit",
        "nonfarm", "initial claims", "jobless", "wage",
        "consumer confidence", "michigan sentiment", "new home",
    ],
    "weather": [
        "temperature", "hurricane", "storm", "rain", "snow", "weather",
        "tornado", "flood", "heat", "cold", "celsius", "fahrenheit",
        "wind", "precipitation", "forecast", "noaa", "nws", "climate",
        "tropical", "wildfire", "drought", "heatwave", "blizzard",
        "high temperature", "low temperature", "rainfall", "snowfall",
    ],
    "politics": [
        "election", "vote", "poll", "president", "congress", "senate",
        "house", "governor", "democrat", "republican", "party",
        "approval", "impeach", "legislation", "bill", "law",
        "cabinet", "supreme court", "primary", "caucus",
        "trump", "biden", "executive order", "tariff", "sanctions",
        "veto", "nomination", "confirmation", "shutdown", "debt ceiling",
    ],
    "crypto": [
        "bitcoin", "btc", "ethereum", "eth", "crypto", "blockchain",
        "defi", "token", "coin", "mining", "wallet", "exchange",
        "solana", "sol", "xrp", "ripple", "dogecoin", "doge",
        "stablecoin", "halving", "etf", "market cap", "altcoin",
    ],
    "entertainment": [
        "oscars", "grammy", "emmy", "golden globe", "box office",
        "movie", "film", "tv", "show", "album", "chart", "billboard",
        "streaming", "netflix", "spotify", "award",
        "reality tv", "bachelor", "survivor", "american idol",
    ],
    "finance": [
        "s&p", "sp500", "nasdaq", "dow jones", "stock", "index",
        "rate cut", "rate hike", "basis points", "bond", "equity",
        "ipo", "revenue", "volatility", "vix", "oil price",
        "crude", "gold price",
    ],
    "science": [
        "spacex", "nasa", "rocket", "launch", "orbit", "mars",
        "moon", "satellite", "ai", "artificial intelligence",
        "fda", "vaccine", "drug approval", "clinical trial",
    ],
}

# Kalshi ticker prefix → category mapping (fast path, no title NLP needed)
KALSHI_PREFIX_CATEGORY = {
    "KXNBA": "sports", "KXNFL": "sports", "KXMLB": "sports",
    "KXNHL": "sports", "KXMLS": "sports", "KXNCAA": "sports",
    "KXUCL": "sports", "KXWBC": "sports", "KXSOC": "sports",
    "KXTEN": "sports", "KXGOL": "sports", "KXUFC": "sports",
    "KXBOX": "sports", "KXF1": "sports", "KXCRIC": "sports",
    "KXBTC": "crypto", "KXETH": "crypto", "KXSOL": "crypto",
    "KXCRY": "crypto", "KXXRP": "crypto", "KXDOG": "crypto",
    "KXCPI": "economics", "KXGDP": "economics", "KXJOB": "economics",
    "KXFED": "economics", "KXINF": "economics", "KXPCE": "economics",
    "KXGAS": "economics", "KXECON": "economics", "KXRATE": "economics",
    "KXTEMP": "weather", "KXHUR": "weather", "KXWX": "weather",
    "KXRAIN": "weather", "KXSNOW": "weather",
    "KXELECT": "politics", "KXPOL": "politics", "KXGOV": "politics",
    "KXTRUMP": "politics", "KXSEN": "politics",
    "KXSP5": "finance", "KXNAS": "finance", "KXDOW": "finance",
    "KXOIL": "finance", "KXGOLD": "finance", "KXVIX": "finance",
    "KXSPX": "finance",
}


def detect_category(title: str, category_hint: str = "", ticker: str = "") -> str:
    """Detect market category from ticker prefix, title, and metadata.
    
    Priority: 1) Kalshi ticker prefix (instant, deterministic)
              2) Kalshi category_hint field
              3) Title keyword matching (fuzzy)
    """
    # Fast path: ticker prefix mapping (deterministic, no NLP)
    if ticker:
        ticker_upper = ticker.upper()
        for prefix, cat in KALSHI_PREFIX_CATEGORY.items():
            if ticker_upper.startswith(prefix):
                return cat

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


# ── Crypto Strategy ──────────────────────────────────────────────────────


class CryptoStrategy(CategoryStrategy):
    """
    Crypto market strategy.

    Key insight: Crypto markets on Kalshi are typically price-range
    or threshold bets (will BTC be above X?). Crypto is highly
    volatile with strong momentum and mean-reversion patterns.

    Approach:
    - High-volume crypto markets are efficient (reduce edge)
    - Very short expiry crypto = high gamma risk, reduce confidence
    - Strong momentum (price_change_5m) increases confidence
    - Extreme midpoints near 0/1 suggest convergence, boost confidence
    """

    @property
    def category(self) -> str:
        return "crypto"

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        adjustment = 0.0
        confidence_boost = 1.0
        reason_parts = []

        # Crypto markets very short-dated = high gamma, reduce confidence
        if features.hours_to_expiry < 1:
            confidence_boost *= 0.65
            reason_parts.append("ultra_short_expiry_gamma")
        elif features.hours_to_expiry < 6:
            confidence_boost *= 0.80
            reason_parts.append("short_expiry_volatile")

        # High-volume crypto = efficient pricing
        if features.volume > 500:
            confidence_boost *= 0.85
            reason_parts.append("high_vol_efficient")

        # Strong momentum signal → slight boost
        if abs(features.price_change_5m) > 0.03:
            confidence_boost *= 1.10
            reason_parts.append("strong_momentum")

        # Near-settled (extreme midpoint) → boost (likely converging)
        if features.prob_distance_from_50 > 0.40:
            confidence_boost *= 1.15
            reason_parts.append("near_settled_convergence")

        return CategoryAdjustment(
            category="crypto",
            adjustment=adjustment,
            confidence_boost=confidence_boost,
            reason="; ".join(reason_parts),
        )


# ── Finance Strategy ─────────────────────────────────────────────────────


class FinanceStrategy(CategoryStrategy):
    """
    Finance/markets strategy (S&P, Nasdaq, VIX, oil, etc.).

    Key insight: Financial index markets track real-time prices of
    underlying assets. The Kalshi market is essentially a digital option.

    Approach:
    - Intraday financial markets are extremely efficient
    - Near-expiry with extreme prices → likely settled, boost confidence
    - Wide spreads in financial markets = arbitrage opportunity
    - Volume ratio spikes = new information arriving
    """

    @property
    def category(self) -> str:
        return "finance"

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        adjustment = 0.0
        confidence_boost = 1.0
        reason_parts = []

        # Financial markets are very efficient — be humble
        confidence_boost *= 0.90
        reason_parts.append("fin_market_efficient")

        # Near-settled financial markets → boost (high conviction)
        if features.hours_to_expiry < 2 and features.prob_distance_from_50 > 0.35:
            confidence_boost *= 1.25
            reason_parts.append("near_settled_high_conviction")

        # Volume spike = new info
        if features.volume_ratio > 3.0:
            confidence_boost *= 0.85
            reason_parts.append("volume_spike_uncertainty")

        return CategoryAdjustment(
            category="finance",
            adjustment=adjustment,
            confidence_boost=confidence_boost,
            reason="; ".join(reason_parts),
        )


# ── Science Strategy ─────────────────────────────────────────────────────


class ScienceStrategy(CategoryStrategy):
    """Science/tech markets (SpaceX launches, FDA approvals, etc.)."""

    @property
    def category(self) -> str:
        return "science"

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
    ) -> CategoryAdjustment:
        adjustment = 0.0
        confidence_boost = 1.0
        reason_parts = []

        # Space launches have binary outcomes — near launch = higher info
        title_lower = (market_title or "").lower()
        if any(w in title_lower for w in ["launch", "spacex", "rocket"]):
            if features.hours_to_expiry < 24:
                confidence_boost *= 1.10
                reason_parts.append("near_launch_high_info")
            else:
                confidence_boost *= 0.75
                reason_parts.append("distant_launch_uncertain")

        # FDA approvals — typically well-telegraphed
        if any(w in title_lower for w in ["fda", "drug", "approval"]):
            confidence_boost *= 0.85
            reason_parts.append("fda_binary_risk")

        return CategoryAdjustment(
            category="science",
            adjustment=adjustment,
            confidence_boost=confidence_boost,
            reason="; ".join(reason_parts),
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
        for cls in [SportsStrategy, EconomicsStrategy, WeatherStrategy,
                     PoliticsStrategy, CryptoStrategy, FinanceStrategy,
                     ScienceStrategy]:
            s = cls()
            self._strategies[s.category] = s
        # Track category distribution for analytics
        self._category_counts: dict[str, int] = {}

    def get(self, category: str) -> CategoryStrategy:
        """Get strategy for a category."""
        return self._strategies.get(category, self._default)

    def adjust_prediction(
        self,
        prediction: Prediction,
        features: MarketFeatures,
        market_title: str = "",
        category_hint: str = "",
        ticker: str = "",
    ) -> tuple[Prediction, CategoryAdjustment]:
        """
        Apply category-specific adjustments to a prediction.

        Returns (adjusted_prediction, adjustment_details).
        """
        category = detect_category(market_title, category_hint, ticker=ticker)
        # Track distribution
        self._category_counts[category] = self._category_counts.get(category, 0) + 1

        strategy = self.get(category)
        adj = strategy.adjust_prediction(prediction, features, market_title)

        # Apply adjustment
        new_prob = max(0.01, min(0.99, prediction.predicted_prob + adj.adjustment))
        new_confidence = max(0.01, min(0.99, prediction.confidence * adj.confidence_boost))

        # Rebuild prediction with adjusted values — preserve ALL fields
        # so that raw_prob, tree_agreement, calibration info survive.
        adjusted = Prediction(
            side=prediction.side,
            confidence=new_confidence,
            predicted_prob=new_prob,
            edge=prediction.edge,  # edge stays the same (it's vs market price)
            model_name=prediction.model_name,
            model_version=prediction.model_version,
            raw_prob=prediction.raw_prob,
            tree_agreement=prediction.tree_agreement,
            prediction_std=prediction.prediction_std,
            calibrated_prob=prediction.calibrated_prob,
            calibration_error=prediction.calibration_error,
            is_calibrated=prediction.is_calibrated,
        )

        return adjusted, adj

    def stats(self) -> dict[str, Any]:
        return {
            "registered_categories": list(self._strategies.keys()),
            "default": self._default.category,
            "category_distribution": dict(self._category_counts),
            "total_classified": sum(self._category_counts.values()),
        }
