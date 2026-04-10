"""
JA Hedge — AI Feature Engineering v2.

World-class 52-feature set for prediction market trading:
- Price-based features (moving averages, RSI, momentum, Bollinger bands)
- Spread/liquidity features (bid-ask dynamics, depth ratios)
- Volume features (volume profiles, OBV, VWAP)
- Time-based features (time-to-expiry curves, urgency, day/hour effects)
- Prediction-market-native features (convergence, log-odds, overround)
- Statistical features (volatility regimes, z-scores, Hurst exponent)
- Cross-feature interactions (price×time, volume×momentum)
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
    # Cyclical time encoding (XGBoost doesn't know hour 23 ≈ hour 0)
    hour_sin: float = 0.0
    hour_cos: float = 1.0
    dow_sin: float = 0.0
    dow_cos: float = 1.0
    # Cross-market: probability sum of sibling markets in same event
    event_prob_sum: float = 1.0  # =1.0 means no arb; >1.0 or <1.0 = mispricing

    # Probability features
    implied_prob: float = 0.5  # midpoint as probability
    prob_distance_from_50: float = 0.0  # abs(prob - 0.5)
    extreme_prob: bool = False  # prob < 0.1 or > 0.9

    # ── Prediction-Market-Native Features (Phase 3) ─────────
    # Time convergence: how fast price is approaching 0 or 100
    convergence_rate: float = 0.0
    # Normalized time: 0.0 = just opened, 1.0 = expiry
    normalized_time: float = 0.0
    # Price × time interaction: extreme prices near expiry = very informative
    price_time_signal: float = 0.0
    # Information arrival rate (price moves per unit time)
    info_rate: float = 0.0
    # Bid-ask spread relative to time-to-expiry (tighter near expiry = more certain)
    spread_time_ratio: float = 0.0
    # Log-odds of current price: ln(p / (1-p))  — linearizes probability space
    log_odds: float = 0.0
    # Overround (market efficiency): how much the yes+no prices exceed $1
    overround: float = 0.0
    # Price acceleration: is convergence speeding up?
    price_acceleration: float = 0.0

    # ── Advanced Statistical Features (Phase 4) ─────────────
    volatility_5: float = 0.0       # rolling 5-tick std dev
    volatility_20: float = 0.0      # rolling 20-tick std dev
    volatility_ratio: float = 1.0   # short/long volatility regime
    bollinger_pct: float = 0.5      # position within Bollinger Bands
    price_zscore: float = 0.0       # z-score vs recent history
    price_bin: float = 0.5          # discretized probability zone
    kelly_edge: float = 0.0         # estimated Kelly sizing edge
    vwap_deviation: float = 0.0     # current price - VWAP
    obv_signal: float = 0.0         # on-balance volume direction
    spread_velocity: float = 0.0    # rate of change of spread
    price_range: float = 0.0        # recent high-low range
    hurst_proxy: float = 0.5        # mean-reversion vs trending
    settlement_confidence: float = 0.0  # market confidence in outcome
    time_urgency: float = 0.0       # exponential urgency near expiry
    volume_momentum: float = 0.0    # volume × momentum interaction

    # ── Phase 5: Elite Edge Features ────────────────────
    oi_velocity: float = 0.0        # rate of change of open interest
    volume_price_trend: float = 0.0 # volume-confirmed price direction
    rsi_divergence: float = 0.0     # price vs RSI divergence signal
    macd_histogram: float = 0.0     # MACD - signal line (momentum shift)
    mean_reversion_signal: float = 0.0  # z-score × Hurst interaction
    smart_money_flow: float = 0.0   # large-volume directional pressure
    edge_decay: float = 0.0         # how fast the edge is shrinking
    price_efficiency: float = 0.0   # how efficiently price moves (vs noise)

    # ── Phase 6: Orderbook Depth Features ─────────────────
    ob_bid_depth: float = 0.0       # total YES-side bid volume (contracts)
    ob_ask_depth: float = 0.0       # total YES-side ask volume (contracts)
    ob_imbalance: float = 0.0       # (bid_depth - ask_depth) / total — directional pressure

    # ── Phase 23: Intelligence Alt-Data Features ──────────
    # Populated by scanner._intelligence_enrich via TickerMapper
    alt_vegas_prob: float = 0.0         # DraftKings/FanDuel implied probability (sports)
    alt_polymarket_prob: float = 0.0    # Polymarket consensus probability
    alt_cross_platform_edge: float = 0.0  # Kalshi price minus external consensus
    alt_crypto_strike_dist: float = 0.0 # (current_price - strike) / strike for crypto markets
    alt_crypto_momentum: float = 0.0    # 24h price change normalised to [-1, 1]
    alt_econ_value: float = 0.0         # Current underlying value (yield, index, etc.)
    alt_econ_strike_dist: float = 0.0   # (current_value - strike) / strike for econ markets
    alt_econ_vix: float = 0.0           # VIX level (fear gauge, normalised 0-1)
    alt_yield_spread: float = 0.0       # 10Y-2Y spread (recession signal)
    alt_news_sentiment: float = 0.0     # News sentiment for this category [-1, 1]
    alt_news_volume: float = 0.0        # Relative news volume (0-1)
    alt_social_sentiment: float = 0.0   # Reddit/social sentiment [-1, 1]
    alt_weather_temp: float = 0.0       # Forecast temperature (°F, normalised)
    alt_weather_extreme: float = 0.0    # Weather extreme score [0, 1]
    alt_source_count: float = 0.0       # How many intelligence sources had data [0, 1]

    # ── Phase 35: Category + Interaction Features ────────
    # Category encoding: lets XGBoost learn per-category behavior
    category_id: float = 0.0            # ordinal category ID (0=unknown, 1=politics, etc.)
    # Cross-feature interactions: XGBoost CAN discover these but converges
    # faster if we pre-compute the most important ones
    vol_confirmed_move: float = 0.0     # price_change_5m × volume_ratio (volume-confirmed direction)
    rsi_time_signal: float = 0.0        # rsi_14 × normalized_time (RSI near expiry = high signal)
    convergence_urgency: float = 0.0    # convergence_rate × time_urgency (convergence speed at expiry)
    momentum_regime: float = 0.0        # macd_histogram × volatility_ratio (momentum in vol context)
    spread_edge: float = 0.0            # spread × hours_to_expiry (liquidity cost vs time value)
    ext_disagreement: float = 0.0       # alt_cross_platform_edge × settlement_confidence

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
                self.hour_sin,
                self.hour_cos,
                self.dow_sin,
                self.dow_cos,
                self.event_prob_sum,
                self.implied_prob,
                self.prob_distance_from_50,
                float(self.extreme_prob),
                # Phase 3: prediction-market-native features
                self.convergence_rate,
                self.normalized_time,
                self.price_time_signal,
                self.info_rate,
                self.spread_time_ratio,
                self.log_odds,
                self.overround,
                self.price_acceleration,
                # Phase 4: advanced statistical features
                self.volatility_5,
                self.volatility_20,
                self.volatility_ratio,
                self.bollinger_pct,
                self.price_zscore,
                self.price_bin,
                self.kelly_edge,
                self.vwap_deviation,
                self.obv_signal,
                self.spread_velocity,
                self.price_range,
                self.hurst_proxy,
                self.settlement_confidence, self.time_urgency, self.volume_momentum,
                # Phase 5: elite edge features
                self.oi_velocity, self.volume_price_trend, self.rsi_divergence,
                self.macd_histogram, self.mean_reversion_signal, self.smart_money_flow,
                self.edge_decay, self.price_efficiency,
                # Phase 6: orderbook depth features
                self.ob_bid_depth, self.ob_ask_depth, self.ob_imbalance,
                # Phase 23: intelligence alt-data features
                self.alt_vegas_prob, self.alt_polymarket_prob,
                self.alt_cross_platform_edge, self.alt_crypto_strike_dist,
                self.alt_crypto_momentum, self.alt_econ_value,
                self.alt_econ_strike_dist, self.alt_econ_vix,
                self.alt_yield_spread, self.alt_news_sentiment,
                self.alt_news_volume, self.alt_social_sentiment,
                self.alt_weather_temp, self.alt_weather_extreme,
                self.alt_source_count,
                # Phase 35: category + interaction features
                self.category_id,
                self.vol_confirmed_move, self.rsi_time_signal,
                self.convergence_urgency, self.momentum_regime,
                self.spread_edge, self.ext_disagreement,
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
            "hour_sin", "hour_cos", "dow_sin", "dow_cos",
            "event_prob_sum",
            "implied_prob", "prob_distance_from_50", "extreme_prob",
            "convergence_rate", "normalized_time", "price_time_signal",
            "info_rate", "spread_time_ratio", "log_odds",
            "overround", "price_acceleration",
            # Phase 4
            "volatility_5", "volatility_20", "volatility_ratio",
            "bollinger_pct", "price_zscore", "price_bin",
            "kelly_edge", "vwap_deviation", "obv_signal",
            "spread_velocity", "price_range", "hurst_proxy",
            "settlement_confidence", "time_urgency", "volume_momentum",
            # Phase 5
            "oi_velocity", "volume_price_trend", "rsi_divergence",
            "macd_histogram", "mean_reversion_signal", "smart_money_flow",
            "edge_decay", "price_efficiency",
            # Phase 6: orderbook depth
            "ob_bid_depth", "ob_ask_depth", "ob_imbalance",
            # Phase 23: intelligence alt-data
            "alt_vegas_prob", "alt_polymarket_prob",
            "alt_cross_platform_edge", "alt_crypto_strike_dist",
            "alt_crypto_momentum", "alt_econ_value",
            "alt_econ_strike_dist", "alt_econ_vix",
            "alt_yield_spread", "alt_news_sentiment",
            "alt_news_volume", "alt_social_sentiment",
            "alt_weather_temp", "alt_weather_extreme",
            "alt_source_count",
            # Phase 35: category + interaction
            "category_id",
            "vol_confirmed_move", "rsi_time_signal",
            "convergence_urgency", "momentum_regime",
            "spread_edge", "ext_disagreement",
        ]


class PriceHistory:
    """Ring buffer of recent prices for a market."""

    def __init__(self, maxlen: int = 2000):
        self.prices: deque[tuple[float, float]] = deque(maxlen=maxlen)  # (timestamp, price)
        self.volumes: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self.oi: deque[tuple[float, float]] = deque(maxlen=maxlen)
        self.spreads: deque[tuple[float, float]] = deque(maxlen=maxlen)

    def add(self, ts: float, price: float, volume: float = 0,
            oi: float = 0, spread: float = 0) -> None:
        self.prices.append((ts, price))
        self.volumes.append((ts, volume))
        self.oi.append((ts, oi))
        self.spreads.append((ts, spread))

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

    def get_spreads(self, n: int) -> list[float]:
        return [s for _, s in list(self.spreads)[-n:]]


class FeatureEngine:
    """
    Computes feature vectors for ML models.

    Maintains a rolling price history per market and computes
    technical indicators on demand.
    """

    def __init__(self) -> None:
        self._histories: dict[str, PriceHistory] = {}
        # Phase 6: Orderbook depth cache — populated by brain._enrich_orderbook_depth()
        self._ob_depth_cache: dict[str, dict[str, float]] = {}

    def update(self, ticker: str, price: float, volume: float = 0,
               oi: float = 0, spread: float = 0) -> None:
        """Push a new price observation for a market."""
        if ticker not in self._histories:
            self._histories[ticker] = PriceHistory()
        import time
        self._histories[ticker].add(time.time(), price, volume, oi, spread)

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

            # MACD signal line (9-period EMA of MACD) — was dead, now fixed
            if features.macd != 0:
                features.signal_line = features.macd * 0.2  # simplified signal approx
                if len(prices_26) >= 26:
                    # Proper: compute MACD history and EMA it
                    macd_hist_vals = []
                    for k in range(min(9, len(prices_26) - 12)):
                        idx = len(prices_26) - 12 - k
                        if idx >= 0:
                            e12 = self._ema(prices_26[idx:idx+12], 12)
                            e26 = self._ema(prices_26[:idx+12], 26) if idx + 12 <= len(prices_26) else features.ema_26
                            macd_hist_vals.append(e12 - e26)
                    if macd_hist_vals:
                        features.signal_line = self._ema(list(reversed(macd_hist_vals)), min(9, len(macd_hist_vals)))

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

            # ── Phase 4: Advanced Statistical Features ──────
            # Volatility (std dev of price changes)
            if len(prices_5) >= 3:
                ret_5 = [prices_5[i] - prices_5[i-1] for i in range(1, len(prices_5))]
                features.volatility_5 = float(np.std(ret_5)) if ret_5 else 0.0
            if len(prices_20) >= 5:
                ret_20 = [prices_20[i] - prices_20[i-1] for i in range(1, len(prices_20))]
                features.volatility_20 = float(np.std(ret_20)) if ret_20 else 0.0
            features.volatility_ratio = (
                features.volatility_5 / max(features.volatility_20, 1e-6)
                if features.volatility_20 > 0 else 1.0
            )

            # Bollinger Band position
            if len(prices_20) >= 5 and features.volatility_20 > 0:
                bb_upper = features.sma_20 + 2 * features.volatility_20
                bb_lower = features.sma_20 - 2 * features.volatility_20
                bb_range = bb_upper - bb_lower
                features.bollinger_pct = max(0.0, min(1.0,
                    (mid - bb_lower) / bb_range if bb_range > 0 else 0.5))

            # Z-score of current price
            if len(prices_20) >= 5:
                mean_20 = sum(prices_20) / len(prices_20)
                std_20 = float(np.std(prices_20))
                features.price_zscore = (mid - mean_20) / max(std_20, 1e-6) if std_20 > 0 else 0.0

            # Price range
            if len(prices_20) >= 3:
                features.price_range = max(prices_20) - min(prices_20)

            # On-balance volume signal
            if len(prices_5) >= 2 and volumes_5 and len(volumes_5) >= 2:
                obv = 0.0
                for i in range(1, min(len(prices_5), len(volumes_5))):
                    if prices_5[i] > prices_5[i-1]:
                        obv += volumes_5[i] if i < len(volumes_5) else 0
                    elif prices_5[i] < prices_5[i-1]:
                        obv -= volumes_5[i] if i < len(volumes_5) else 0
                max_vol = max(volumes_5) if volumes_5 else 1.0
                features.obv_signal = max(-1.0, min(1.0,
                    obv / max(max_vol * len(volumes_5), 1.0)))

            # Spread velocity
            spreads_5 = hist.get_spreads(5)
            if len(spreads_5) >= 2:
                features.spread_velocity = spreads_5[-1] - spreads_5[0]

            # Hurst exponent proxy
            if len(prices_20) >= 10:
                features.hurst_proxy = self._hurst_proxy(prices_20)

            # Volume-momentum interaction
            features.volume_momentum = features.volume_ratio * features.price_change_5m

        # Volume / OI from market
        features.volume = float(market.volume or 0)
        features.open_interest = float(market.open_interest or 0)

        # OI change — was dead, now computed from history
        if hist and len(hist.oi) >= 2:
            oi_list = [o for _, o in list(hist.oi)[-5:]]
            if len(oi_list) >= 2:
                features.oi_change = oi_list[-1] - oi_list[0]

        # Book imbalance — was dead, now computed from bid/ask depth
        if market.yes_bid is not None and market.yes_ask is not None:
            bid_d = float(market.yes_bid or 0)
            ask_d = float(market.yes_ask or 0)
            total_d = bid_d + ask_d
            features.book_imbalance = (bid_d - ask_d) / total_d if total_d > 0 else 0.0

        # Phase 6: Orderbook depth features (injected by brain before compute)
        # These come from _ob_depth_cache populated by brain._enrich_orderbook_depth
        ob_data = self._ob_depth_cache.get(market.ticker)
        if ob_data:
            features.ob_bid_depth = ob_data.get("bid_depth", 0.0)
            features.ob_ask_depth = ob_data.get("ask_depth", 0.0)
            features.ob_imbalance = ob_data.get("imbalance", 0.0)

        # Time features
        if market.expiration_time:
            delta = (market.expiration_time - now).total_seconds() / 3600
            features.hours_to_expiry = max(delta, 0)
            features.time_decay_factor = (
                1.0 / math.sqrt(max(features.hours_to_expiry, 0.01))
            )

        features.hour_of_day = now.hour
        features.day_of_week = now.weekday()

        # Cyclical time encoding: sin/cos so XGBoost knows hour 23 ≈ hour 0
        features.hour_sin = math.sin(2.0 * math.pi * now.hour / 24.0)
        features.hour_cos = math.cos(2.0 * math.pi * now.hour / 24.0)
        features.dow_sin = math.sin(2.0 * math.pi * now.weekday() / 7.0)
        features.dow_cos = math.cos(2.0 * math.pi * now.weekday() / 7.0)

        # Cross-market event probability sum (populated externally by brain)
        # Default 1.0 = no mispricing detected

        # Probability features
        features.implied_prob = mid
        features.prob_distance_from_50 = abs(mid - 0.5)
        features.extreme_prob = mid < 0.1 or mid > 0.9

        # ── Phase 3: Prediction-Market-Native Features ────────
        # Log-odds: linearizes probability space (key for ML)
        clamped = max(0.01, min(0.99, mid))
        features.log_odds = math.log(clamped / (1.0 - clamped))

        # Convergence rate: how fast price is moving toward 0 or 100
        if hist and len(hist.prices) >= 10:
            recent = hist.get_prices(10)
            dist_now = abs(recent[-1] - 0.5) if recent else 0
            dist_old = abs(recent[0] - 0.5) if recent else 0
            features.convergence_rate = dist_now - dist_old  # positive = converging faster

        # Normalized time: 0 = opened, 1 = expiry
        if market.open_time and market.expiration_time:
            total = (market.expiration_time - market.open_time).total_seconds()
            elapsed = (now - market.open_time).total_seconds()
            features.normalized_time = max(0.0, min(1.0, elapsed / total)) if total > 0 else 0.5

        # Price × time interaction: extreme prices near expiry are very informative
        features.price_time_signal = features.prob_distance_from_50 * features.normalized_time

        # Information arrival rate: absolute price changes per time period
        if hist and len(hist.prices) >= 5:
            prices_5 = hist.get_prices(5)
            abs_changes = [abs(prices_5[i] - prices_5[i-1]) for i in range(1, len(prices_5))]
            features.info_rate = sum(abs_changes) / max(len(abs_changes), 1)

        # Spread × time ratio: tighter spread near expiry = more certainty
        if features.hours_to_expiry > 0:
            features.spread_time_ratio = features.spread / max(features.hours_to_expiry, 0.01)

        # Overround: sum of yes_ask + no_ask - 1 (market efficiency)
        if market.yes_ask is not None and market.no_ask is not None:
            features.overround = float(market.yes_ask) + float(market.no_ask) - 1.0

        # Price acceleration: 2nd derivative of price
        if hist and len(hist.prices) >= 20:
            recent_20 = hist.get_prices(20)
            mid_idx = len(recent_20) // 2
            vel_recent = recent_20[-1] - recent_20[mid_idx] if mid_idx > 0 else 0
            vel_old = recent_20[mid_idx] - recent_20[0] if mid_idx > 0 else 0
            features.price_acceleration = vel_recent - vel_old

        # ── Phase 4: Additional Advanced Features ────────────
        # Price bin (discretized zone — helps model learn non-linear price effects)
        features.price_bin = round(mid * 10) / 10

        # Kelly edge estimate
        features.kelly_edge = abs(mid - 0.5) * 2 * features.time_decay_factor * 0.1

        # VWAP deviation
        if hist and len(hist.prices) >= 5:
            pl = hist.get_prices(10)
            vl = hist.get_volumes(10)
            if pl and vl and len(vl) >= len(pl):
                tv = sum(vl[:len(pl)]) or 1.0
                vwap = sum(p * v for p, v in zip(pl, vl[:len(pl)])) / tv
                features.vwap_deviation = mid - vwap

        # Settlement confidence: how close price is to 0 or 1
        features.settlement_confidence = 2 * abs(mid - 0.5)

        # Time urgency: exponential urgency near expiry
        features.time_urgency = math.exp(-features.hours_to_expiry / 24.0) if features.hours_to_expiry >= 0 else 0.0

        # ── Phase 5: Elite Edge Features ─────────────────────
        # OI velocity: rate of change of open interest (institutional flow proxy)
        if hist and len(hist.oi) >= 5:
            oi_vals = [o for _, o in list(hist.oi)[-10:]]
            if len(oi_vals) >= 2:
                features.oi_velocity = (oi_vals[-1] - oi_vals[0]) / max(len(oi_vals), 1)

        # Volume-price trend: confirms whether volume supports direction
        if features.price_velocity != 0 and features.volume_ratio != 1.0:
            direction = 1.0 if features.price_velocity > 0 else -1.0
            features.volume_price_trend = direction * features.volume_ratio

        # RSI divergence: price makes new high but RSI doesn't (bearish) or vice versa
        if hist and len(hist.prices) >= 20:
            p_recent = hist.get_prices(20)
            half = len(p_recent) // 2
            p_first, p_second = p_recent[:half], p_recent[half:]
            if len(p_first) >= 7 and len(p_second) >= 7:
                rsi_first = self._rsi(p_first[-14:] if len(p_first) >= 14 else p_first)
                rsi_second = self._rsi(p_second[-14:] if len(p_second) >= 14 else p_second)
                price_delta = (sum(p_second) / len(p_second)) - (sum(p_first) / len(p_first))
                rsi_delta = rsi_second - rsi_first
                # Divergence: price up but RSI down (or vice versa)
                if abs(price_delta) > 0.001:
                    features.rsi_divergence = -price_delta * rsi_delta / 100.0

        # MACD histogram: captures momentum acceleration (MACD - signal)
        features.macd_histogram = features.macd - features.signal_line

        # Mean-reversion signal: z-score × Hurst interaction
        # High z-score + low Hurst (mean-reverting) = strong reversion expected
        features.mean_reversion_signal = features.price_zscore * (1.0 - features.hurst_proxy)

        # Smart money flow: high-volume moves in a direction = smart money
        if hist and len(hist.prices) >= 5:
            p5_vals = hist.get_prices(5)
            v5_vals = hist.get_volumes(5)
            if len(p5_vals) >= 2 and len(v5_vals) >= 2:
                flow = 0.0
                avg_v = sum(v5_vals) / len(v5_vals) if v5_vals else 1.0
                for i in range(1, min(len(p5_vals), len(v5_vals))):
                    direction = 1.0 if p5_vals[i] > p5_vals[i-1] else -1.0
                    weight = v5_vals[i] / max(avg_v, 1.0)  # higher vol = more weight
                    flow += direction * weight
                features.smart_money_flow = max(-3.0, min(3.0, flow))

        # Edge decay: how fast the probability edge is shrinking over time
        if hist and len(hist.prices) >= 10:
            p10 = hist.get_prices(10)
            edge_old = abs(p10[0] - 0.5)
            edge_new = abs(p10[-1] - 0.5)
            features.edge_decay = edge_new - edge_old  # negative = edge shrinking

        # Price efficiency: ratio of net price move to total absolute moves
        if hist and len(hist.prices) >= 10:
            p10 = hist.get_prices(10)
            net_move = abs(p10[-1] - p10[0])
            total_move = sum(abs(p10[i] - p10[i-1]) for i in range(1, len(p10)))
            features.price_efficiency = net_move / max(total_move, 1e-6) if total_move > 0 else 0.0

        # ── Phase 35: Category Encoding ───────────────────
        # Ordinal encoding — XGBoost can split on this to learn per-category patterns.
        # Categories mapped to stable integer IDs.
        _cat_str = getattr(market, 'category', '') or ''
        _title_str = getattr(market, 'title', '') or ''
        _cat_map = {
            'politics': 1, 'economics': 2, 'finance': 3, 'crypto': 4,
            'sports': 5, 'entertainment': 6, 'science': 7, 'weather': 8,
            'social_media': 9, 'tech': 10, 'health': 11, 'legal': 12,
        }
        _cat_lower = _cat_str.lower()
        features.category_id = float(_cat_map.get(_cat_lower, 0))
        # Also try to detect from title/ticker if category field is empty
        if features.category_id == 0:
            _t_low = _title_str.lower() + ' ' + market.ticker.lower()
            for kw, cid in [('nba', 5), ('nfl', 5), ('mlb', 5), ('nhl', 5),
                            ('bitcoin', 4), ('btc', 4), ('eth', 4), ('crypto', 4),
                            ('trump', 1), ('biden', 1), ('election', 1), ('congress', 1),
                            ('fed ', 2), ('rate', 2), ('gdp', 2), ('cpi', 2),
                            ('weather', 8), ('temperature', 8), ('rain', 8),
                            ('s&p', 3), ('nasdaq', 3), ('dow', 3), ('stock', 3)]:
                if kw in _t_low:
                    features.category_id = float(cid)
                    break

        # ── Phase 35: Interaction Features ────────────────
        # These encode the most predictive non-linear relationships.
        # XGBoost can discover these itself, but pre-computing them
        # means it needs fewer trees / less depth to find the pattern.
        features.vol_confirmed_move = features.price_change_5m * features.volume_ratio
        features.rsi_time_signal = (features.rsi_14 / 100.0) * features.normalized_time
        features.convergence_urgency = features.convergence_rate * features.time_urgency
        features.momentum_regime = features.macd_histogram * features.volatility_ratio
        features.spread_edge = features.spread * max(features.hours_to_expiry, 0.01)
        features.ext_disagreement = features.alt_cross_platform_edge * features.settlement_confidence

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

    @staticmethod
    def _hurst_proxy(prices: list[float]) -> float:
        """
        Simplified Hurst exponent estimation.
        < 0.5 = mean-reverting, = 0.5 = random walk, > 0.5 = trending.
        """
        if len(prices) < 5:
            return 0.5
        try:
            returns = [prices[i] - prices[i-1] for i in range(1, len(prices))]
            n = len(returns)
            mean_r = sum(returns) / n
            cumulative = []
            s = 0.0
            for d in (r - mean_r for r in returns):
                s += d
                cumulative.append(s)
            R = max(cumulative) - min(cumulative)
            S = float(np.std(returns))
            if S < 1e-10:
                return 0.5
            RS = R / S
            if RS <= 0 or n <= 1:
                return 0.5
            H = math.log(RS) / math.log(n)
            return max(0.0, min(1.0, H))
        except Exception:
            return 0.5
