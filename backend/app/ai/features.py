"""
JA Hedge — AI Feature Engineering.

Computes trading features from raw market data for ML models:
- Price-based features (moving averages, RSI, momentum)
- Spread/liquidity features
- Volume features
- Time-based features (time-to-expiry, hour-of-day)
- Cross-market correlation features
- Orderbook imbalance features
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import numpy as np

from app.kalshi.models import Market
from app.logging_config import get_logger
from app.pipeline import market_cache

log = get_logger("ai.features")


@dataclass
class MarketFeatures:
    """Computed feature vector for a single market at a point in time."""

    ticker: str
    timestamp: datetime

    # Price features
    midpoint: float = 0.0
    spread: float = 0.0
    spread_pct: float = 0.0
    last_price: float = 0.0
    price_change_1m: float = 0.0
    price_change_5m: float = 0.0
    price_change_15m: float = 0.0
    price_velocity: float = 0.0  # rate of change

    # Moving averages
    sma_5: float = 0.0
    sma_20: float = 0.0
    ema_12: float = 0.0
    ema_26: float = 0.0
    macd: float = 0.0
    signal_line: float = 0.0

    # Momentum / oscillators
    rsi_14: float = 50.0
    momentum_10: float = 0.0

    # Volume features
    volume: float = 0.0
    volume_ma_5: float = 0.0
    volume_ratio: float = 1.0  # current / avg
    open_interest: float = 0.0
    oi_change: float = 0.0

    # Liquidity
    bid_depth: float = 0.0
    ask_depth: float = 0.0
    book_imbalance: float = 0.0  # (bid_depth - ask_depth) / total

    # Time features
    hours_to_expiry: float = 0.0
    time_decay_factor: float = 0.0  # 1/sqrt(hours_to_expiry)
    hour_of_day: int = 0
    day_of_week: int = 0
    is_market_hours: bool = True

    # Probability features
    implied_prob: float = 0.5  # midpoint as probability
    prob_distance_from_50: float = 0.0  # abs(prob - 0.5)
    extreme_prob: bool = False  # prob < 0.1 or > 0.9

    def to_array(self) -> np.ndarray:
        """Convert to numpy array for ML model input."""
        return np.array(
            [
                self.midpoint,
                self.spread,
                self.spread_pct,
                self.last_price,
                self.price_change_1m,
                self.price_change_5m,
                self.price_change_15m,
                self.price_velocity,
                self.sma_5,
                self.sma_20,
                self.ema_12,
                self.ema_26,
                self.macd,
                self.signal_line,
                self.rsi_14,
                self.momentum_10,
                self.volume,
                self.volume_ma_5,
                self.volume_ratio,
                self.open_interest,
                self.oi_change,
                self.book_imbalance,
                self.hours_to_expiry,
                self.time_decay_factor,
                self.hour_of_day,
                self.day_of_week,
                self.implied_prob,
                self.prob_distance_from_50,
                float(self.extreme_prob),
            ],
            dtype=np.float32,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for JSON storage (AI signals table)."""
        return {
            k: v
            for k, v in self.__dict__.items()
            if k not in ("ticker", "timestamp") and not k.startswith("_")
        }

    @classmethod
    def feature_names(cls) -> list[str]:
        return [
            "midpoint", "spread", "spread_pct", "last_price",
            "price_change_1m", "price_change_5m", "price_change_15m",
            "price_velocity", "sma_5", "sma_20", "ema_12", "ema_26",
            "macd", "signal_line", "rsi_14", "momentum_10",
            "volume", "volume_ma_5", "volume_ratio", "open_interest",
            "oi_change", "book_imbalance", "hours_to_expiry",
            "time_decay_factor", "hour_of_day", "day_of_week",
            "implied_prob", "prob_distance_from_50", "extreme_prob",
        ]


class PriceHistory:
    """Ring buffer of recent prices for a market."""

    def __init__(self, maxlen: int = 1000):
        self.prices: deque[tuple[float, float]] = deque(maxlen=maxlen)  # (timestamp, price)
        self.volumes: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self.oi: deque[tuple[float, float]] = deque(maxlen=maxlen)

    def add(self, ts: float, price: float, volume: float = 0, oi: float = 0) -> None:
        self.prices.append((ts, price))
        self.volumes.append((ts, volume))
        self.oi.append((ts, oi))

    def get_price_at(self, minutes_ago: float) -> float | None:
        """Get price approximately N minutes ago."""
        target_ts = self.prices[-1][0] - (minutes_ago * 60) if self.prices else 0
        for ts, price in reversed(self.prices):
            if ts <= target_ts:
                return price
        return self.prices[0][1] if self.prices else None

    def get_prices(self, n: int) -> list[float]:
        """Get last N prices."""
        return [p for _, p in list(self.prices)[-n:]]

    def get_volumes(self, n: int) -> list[float]:
        return [v for _, v in list(self.volumes)[-n:]]


class FeatureEngine:
    """
    Computes feature vectors for ML models.

    Maintains a rolling price history per market and computes
    technical indicators on demand.
    """

    def __init__(self) -> None:
        self._histories: dict[str, PriceHistory] = {}

    def update(self, ticker: str, price: float, volume: float = 0, oi: float = 0) -> None:
        """Push a new price observation for a market."""
        if ticker not in self._histories:
            self._histories[ticker] = PriceHistory()
        import time
        self._histories[ticker].add(time.time(), price, volume, oi)

    def compute(self, market: Market) -> MarketFeatures:
        """Compute full feature vector for a market."""
        now = datetime.now(timezone.utc)
        features = MarketFeatures(ticker=market.ticker, timestamp=now)

        # Price features
        mid = float(market.midpoint or market.last_price or Decimal("0.5"))
        features.midpoint = mid
        features.last_price = float(market.last_price or 0)
        features.spread = float(market.spread or 0)
        features.spread_pct = features.spread / mid if mid > 0 else 0

        # History-based features
        hist = self._histories.get(market.ticker)
        if hist and len(hist.prices) >= 2:
            # Price changes
            p1 = hist.get_price_at(1)
            p5 = hist.get_price_at(5)
            p15 = hist.get_price_at(15)
            if p1 is not None:
                features.price_change_1m = mid - p1
            if p5 is not None:
                features.price_change_5m = mid - p5
            if p15 is not None:
                features.price_change_15m = mid - p15

            # Velocity (price change per minute)
            prices = hist.get_prices(10)
            if len(prices) >= 2:
                features.price_velocity = (prices[-1] - prices[0]) / max(len(prices) - 1, 1)

            # Moving averages
            prices_20 = hist.get_prices(20)
            prices_5 = hist.get_prices(5)
            if prices_5:
                features.sma_5 = sum(prices_5) / len(prices_5)
            if prices_20:
                features.sma_20 = sum(prices_20) / len(prices_20)

            # EMA
            prices_26 = hist.get_prices(26)
            if len(prices_26) >= 12:
                features.ema_12 = self._ema(prices_26[-12:], 12)
            if len(prices_26) >= 26:
                features.ema_26 = self._ema(prices_26, 26)
            features.macd = features.ema_12 - features.ema_26

            # RSI
            prices_14 = hist.get_prices(15)
            if len(prices_14) >= 14:
                features.rsi_14 = self._rsi(prices_14[-14:])

            # Momentum
            prices_10 = hist.get_prices(11)
            if len(prices_10) >= 10:
                features.momentum_10 = prices_10[-1] - prices_10[0]

            # Volume features
            volumes_5 = hist.get_volumes(5)
            if volumes_5:
                features.volume_ma_5 = sum(volumes_5) / len(volumes_5)
                features.volume_ratio = (
                    volumes_5[-1] / features.volume_ma_5
                    if features.volume_ma_5 > 0
                    else 1.0
                )

        # Volume / OI from market
        features.volume = float(market.volume or 0)
        features.open_interest = float(market.open_interest or 0)

        # Time features
        if market.expiration_time:
            delta = (market.expiration_time - now).total_seconds() / 3600
            features.hours_to_expiry = max(delta, 0)
            features.time_decay_factor = (
                1.0 / math.sqrt(max(features.hours_to_expiry, 0.01))
            )

        features.hour_of_day = now.hour
        features.day_of_week = now.weekday()

        # Probability features
        features.implied_prob = mid
        features.prob_distance_from_50 = abs(mid - 0.5)
        features.extreme_prob = mid < 0.1 or mid > 0.9

        return features

    @staticmethod
    def _ema(prices: list[float], period: int) -> float:
        """Compute exponential moving average."""
        if not prices:
            return 0.0
        multiplier = 2 / (period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema

    @staticmethod
    def _rsi(prices: list[float], period: int = 14) -> float:
        """Compute RSI (Relative Strength Index)."""
        if len(prices) < 2:
            return 50.0

        gains, losses = [], []
        for i in range(1, len(prices)):
            delta = prices[i] - prices[i - 1]
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))

        avg_gain = sum(gains) / len(gains) if gains else 0
        avg_loss = sum(losses) / len(losses) if losses else 0

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
