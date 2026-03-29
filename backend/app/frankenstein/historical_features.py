"""
Frankenstein — Historical Feature Engineering (Phase 2).

Computes real 68-feature vectors from historical candlestick data
stored in the SQLite database. Each settled market produces multiple
training samples at different time slices (e.g., 50%, 30%, 10% time
remaining), all sharing the same label (yes/no outcome).

This is the CRITICAL difference from the old bootstrap.py: features
are computed from REAL market data (bid/ask OHLC, volume, OI over time),
not synthetic random values.

Usage:
    from app.frankenstein.historical_features import build_training_dataset
    X, y, meta = build_training_dataset()
"""

from __future__ import annotations

import math
import sqlite3
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.logging_config import get_logger

log = get_logger("frankenstein.historical_features")

# Time slices: fraction of total market duration at which we compute features.
# 0.50 = halfway through the market's life, 0.10 = 90% of the way to expiry.
# More slices = more training data, but they're correlated within a market.
DEFAULT_TIME_SLICES = [0.50, 0.30, 0.15, 0.08]

# Minimum candles needed to compute meaningful features
MIN_CANDLES_PER_SLICE = 5


def _compute_sma(prices: list[float], window: int) -> float:
    """Simple Moving Average over the last `window` prices."""
    if len(prices) < window:
        return prices[-1] if prices else 0.0
    return sum(prices[-window:]) / window


def _compute_ema(prices: list[float], window: int) -> float:
    """Exponential Moving Average."""
    if not prices:
        return 0.0
    if len(prices) < window:
        return sum(prices) / len(prices)
    alpha = 2.0 / (window + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1 - alpha) * ema
    return ema


def _compute_rsi(prices: list[float], window: int = 14) -> float:
    """Relative Strength Index (0-100)."""
    if len(prices) < window + 1:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent = deltas[-window:]
    gains = [d for d in recent if d > 0]
    losses = [-d for d in recent if d < 0]
    avg_gain = sum(gains) / window if gains else 0.0001
    avg_loss = sum(losses) / window if losses else 0.0001
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def _compute_bollinger_pct(prices: list[float], window: int = 20) -> float:
    """Position within Bollinger Bands (0=lower, 1=upper)."""
    if len(prices) < window:
        return 0.5
    recent = prices[-window:]
    mean = sum(recent) / len(recent)
    std = (sum((p - mean) ** 2 for p in recent) / len(recent)) ** 0.5
    if std < 0.0001:
        return 0.5
    upper = mean + 2 * std
    lower = mean - 2 * std
    band_width = upper - lower
    if band_width < 0.0001:
        return 0.5
    return max(0.0, min(1.0, (prices[-1] - lower) / band_width))


def _compute_hurst(prices: list[float], max_lag: int = 20) -> float:
    """Hurst exponent proxy. <0.5=mean-reverting, >0.5=trending."""
    if len(prices) < max_lag + 2:
        return 0.5
    series = np.array(prices[-max_lag - 2:])
    lags = range(2, min(max_lag, len(series) // 2))
    tau = []
    for lag in lags:
        diff = series[lag:] - series[:-lag]
        std = np.std(diff)
        if std > 0:
            tau.append(std)
        else:
            tau.append(0.0001)
    if len(tau) < 2:
        return 0.5
    log_lags = np.log(list(lags)[:len(tau)])
    log_tau = np.log(np.array(tau))
    if len(log_lags) < 2:
        return 0.5
    poly = np.polyfit(log_lags, log_tau, 1)
    return max(0.0, min(1.0, poly[0]))


def _compute_obv_signal(prices: list[float], volumes: list[float]) -> float:
    """On-Balance Volume direction signal (-1 to 1)."""
    if len(prices) < 2 or len(volumes) < 2:
        return 0.0
    n = min(len(prices), len(volumes))
    obv = 0.0
    for i in range(1, n):
        if prices[i] > prices[i - 1]:
            obv += volumes[i]
        elif prices[i] < prices[i - 1]:
            obv -= volumes[i]
    # Normalize by total volume
    total_vol = sum(volumes[-n:]) or 1.0
    return max(-1.0, min(1.0, obv / total_vol))


def _compute_smart_money_flow(
    prices: list[float], volumes: list[float], threshold_pct: float = 0.75
) -> float:
    """Large-volume directional pressure."""
    if len(prices) < 2 or len(volumes) < 2:
        return 0.0
    n = min(len(prices), len(volumes))
    if n < 5:
        return 0.0
    vol_threshold = sorted(volumes[-n:], reverse=True)[max(0, int(n * (1 - threshold_pct)))]
    smart_flow = 0.0
    total_smart = 0.0
    for i in range(1, n):
        if volumes[i] >= vol_threshold:
            direction = 1.0 if prices[i] > prices[i - 1] else -1.0
            smart_flow += direction * volumes[i]
            total_smart += volumes[i]
    if total_smart <= 0:
        return 0.0
    return max(-1.0, min(1.0, smart_flow / total_smart))


def compute_features_from_candles(
    candles: list[dict[str, Any]],
    slice_index: int,
    total_candles: int,
    hours_to_expiry: float,
    total_duration_hours: float,
    result: str,
) -> MarketFeatures | None:
    """
    Compute a full MarketFeatures vector from historical candle data.

    Args:
        candles: List of candle dicts up to the slice point (ordered by time).
        slice_index: Index of the last candle to include.
        total_candles: Total candles in the market.
        hours_to_expiry: Hours remaining at this slice.
        total_duration_hours: Total market duration in hours.
        result: Market result ('yes' or 'no').

    Returns:
        MarketFeatures instance or None if insufficient data.
    """
    if len(candles) < MIN_CANDLES_PER_SLICE:
        return None

    # Extract price series (use bid/ask midpoint where available, fallback to price_close)
    prices: list[float] = []
    volumes: list[float] = []
    ois: list[float] = []
    spreads: list[float] = []
    bid_prices: list[float] = []
    ask_prices: list[float] = []

    for c in candles:
        bid_c = c.get("bid_close") or 0
        ask_c = c.get("ask_close") or 0

        if bid_c and ask_c and bid_c > 0 and ask_c > 0:
            mid = (float(bid_c) + float(ask_c)) / 2.0
            spread = float(ask_c) - float(bid_c)
        elif c.get("price_close") and float(c["price_close"]) > 0:
            mid = float(c["price_close"])
            spread = 0.0
        else:
            continue

        # Normalize to 0-1 range (Kalshi prices can be in cents)
        if mid > 1.5:
            mid = mid / 100.0
            spread = spread / 100.0
            if bid_c and float(bid_c) > 1.5:
                bid_c = float(bid_c) / 100.0
            if ask_c and float(ask_c) > 1.5:
                ask_c = float(ask_c) / 100.0

        prices.append(mid)
        volumes.append(float(c.get("volume") or 0))
        ois.append(float(c.get("open_interest") or 0))
        spreads.append(max(spread, 0))
        bid_prices.append(float(bid_c) if bid_c else mid)
        ask_prices.append(float(ask_c) if ask_c else mid)

    if len(prices) < MIN_CANDLES_PER_SLICE:
        return None

    # Current values
    current_price = prices[-1]
    current_spread = spreads[-1] if spreads else 0.0
    current_volume = volumes[-1] if volumes else 0.0
    current_oi = ois[-1] if ois else 0.0

    # Price changes
    price_change_1m = prices[-1] - prices[-2] if len(prices) >= 2 else 0.0
    price_change_5m = prices[-1] - prices[-6] if len(prices) >= 6 else 0.0
    price_change_15m = prices[-1] - prices[-16] if len(prices) >= 16 else 0.0

    # Moving averages
    sma_5 = _compute_sma(prices, 5)
    sma_20 = _compute_sma(prices, 20)
    ema_12 = _compute_ema(prices, 12)
    ema_26 = _compute_ema(prices, 26)
    macd = ema_12 - ema_26
    signal_line = _compute_ema([ema_12 - ema_26] * min(9, len(prices)), 9)  # approximate

    # RSI
    rsi_14 = _compute_rsi(prices, 14)

    # Momentum
    momentum_10 = prices[-1] - prices[-11] if len(prices) >= 11 else 0.0

    # Volume
    vol_ma_5 = _compute_sma(volumes, 5)
    volume_ratio = current_volume / vol_ma_5 if vol_ma_5 > 0 else 1.0

    # OI change
    oi_change = ois[-1] - ois[-2] if len(ois) >= 2 else 0.0

    # Book imbalance (from bid/ask)
    bid_depth = bid_prices[-1] if bid_prices else 0.0
    ask_depth = ask_prices[-1] if ask_prices else 0.0

    # Time features
    now_fake = datetime.now(timezone.utc)
    hour_of_day = (candles[-1].get("end_period_ts", 0) // 3600) % 24
    day_of_week = ((candles[-1].get("end_period_ts", 0) // 86400) + 4) % 7  # Unix epoch was Thursday

    # Cyclical time encoding
    hour_sin = math.sin(2 * math.pi * hour_of_day / 24)
    hour_cos = math.cos(2 * math.pi * hour_of_day / 24)
    dow_sin = math.sin(2 * math.pi * day_of_week / 7)
    dow_cos = math.cos(2 * math.pi * day_of_week / 7)

    # Time decay
    time_decay_factor = 1.0 / math.sqrt(max(hours_to_expiry, 0.01))

    # Probability features
    implied_prob = max(0.01, min(0.99, current_price))
    prob_distance = abs(implied_prob - 0.5)
    extreme_prob = implied_prob < 0.10 or implied_prob > 0.90

    # Prediction-market-native features
    normalized_time = 1.0 - (hours_to_expiry / max(total_duration_hours, 0.01))
    normalized_time = max(0.0, min(1.0, normalized_time))

    # Convergence rate
    if len(prices) >= 10:
        convergence_rate = abs(prices[-1] - 0.5) - abs(prices[-10] - 0.5)
        convergence_rate /= 10.0
    else:
        convergence_rate = 0.0

    # Price-time signal
    price_time_signal = prob_distance * normalized_time

    # Info rate
    if len(prices) >= 5:
        changes = [abs(prices[i] - prices[i - 1]) for i in range(-min(5, len(prices)) + 1, 0)]
        info_rate = sum(changes) / max(len(changes), 1)
    else:
        info_rate = 0.0

    # Spread-time ratio
    spread_time_ratio = current_spread / max(hours_to_expiry, 0.01)

    # Log-odds
    clamped = max(0.01, min(0.99, implied_prob))
    log_odds = math.log(clamped / (1 - clamped))

    # Overround (if we have bid/ask for both sides)
    overround = 0.0
    if bid_prices and ask_prices:
        overround = max(0.0, ask_prices[-1] + (1.0 - bid_prices[-1]) - 1.0)

    # Price acceleration
    if len(prices) >= 20:
        rate_recent = abs(prices[-1] - prices[-5]) / 5.0
        rate_older = abs(prices[-10] - prices[-15]) / 5.0
        price_acceleration = rate_recent - rate_older
    else:
        price_acceleration = 0.0

    # Volatility
    if len(prices) >= 5:
        volatility_5 = float(np.std(prices[-5:]))
    else:
        volatility_5 = 0.0
    if len(prices) >= 20:
        volatility_20 = float(np.std(prices[-20:]))
    else:
        volatility_20 = volatility_5
    volatility_ratio = volatility_5 / max(volatility_20, 0.0001)

    # Bollinger %
    bollinger_pct = _compute_bollinger_pct(prices, 20)

    # Z-score
    if len(prices) >= 20:
        mean20 = sum(prices[-20:]) / 20
        std20 = max(volatility_20, 0.0001)
        price_zscore = (prices[-1] - mean20) / std20
    else:
        price_zscore = 0.0

    # Price bin
    price_bin = max(0.0, min(1.0, round(implied_prob * 10) / 10))

    # Kelly edge (raw, pre-fee)
    kelly_edge = abs(implied_prob - 0.5) if abs(implied_prob - 0.5) > 0.05 else 0.0

    # VWAP deviation
    if volumes and sum(volumes) > 0:
        vwap = sum(p * v for p, v in zip(prices, volumes)) / sum(volumes)
        vwap_deviation = prices[-1] - vwap
    else:
        vwap_deviation = 0.0

    # OBV signal
    obv_signal = _compute_obv_signal(prices, volumes)

    # Spread velocity
    if len(spreads) >= 5:
        spread_velocity = spreads[-1] - spreads[-5]
    else:
        spread_velocity = 0.0

    # Price range
    if len(prices) >= 20:
        price_range = max(prices[-20:]) - min(prices[-20:])
    else:
        price_range = max(prices) - min(prices) if prices else 0.0

    # Hurst proxy
    hurst_proxy = _compute_hurst(prices, 20)

    # Settlement confidence
    settlement_confidence = prob_distance * (1.0 + normalized_time)
    settlement_confidence = min(1.0, settlement_confidence)

    # Time urgency
    time_urgency = math.exp(-hours_to_expiry / 2.0) if hours_to_expiry > 0 else 1.0

    # Volume momentum
    volume_momentum = volume_ratio * momentum_10

    # Phase 5 features
    if len(ois) >= 5:
        oi_velocity = ois[-1] - ois[-5]
    else:
        oi_velocity = 0.0

    # Volume-price trend
    if len(prices) >= 5 and len(volumes) >= 5:
        vpt = 0.0
        for i in range(-4, 0):
            if prices[i - 1] != 0:
                vpt += volumes[i] * (prices[i] - prices[i - 1]) / prices[i - 1]
        volume_price_trend = vpt
    else:
        volume_price_trend = 0.0

    # RSI divergence
    if len(prices) >= 14:
        rsi_now = _compute_rsi(prices, 14)
        rsi_prev = _compute_rsi(prices[:-5], 14) if len(prices) >= 19 else rsi_now
        price_trend = 1.0 if prices[-1] > prices[-6] else -1.0 if len(prices) >= 6 else 0.0
        rsi_trend = 1.0 if rsi_now > rsi_prev else -1.0
        rsi_divergence = 1.0 if price_trend != rsi_trend else 0.0
    else:
        rsi_divergence = 0.0

    # MACD histogram
    macd_histogram = macd - signal_line

    # Mean reversion signal
    mean_reversion_signal = price_zscore * (1.0 - hurst_proxy)

    # Smart money flow
    smart_money_flow = _compute_smart_money_flow(prices, volumes)

    # Edge decay
    if len(prices) >= 10:
        edge_5_ago = abs(prices[-5] - 0.5) - abs(sma_20 - 0.5) if sma_20 else 0
        edge_now = abs(prices[-1] - 0.5) - abs(sma_20 - 0.5) if sma_20 else 0
        edge_decay = edge_now - edge_5_ago
    else:
        edge_decay = 0.0

    # Price efficiency
    if len(prices) >= 10:
        net_move = abs(prices[-1] - prices[-10])
        total_move = sum(abs(prices[i] - prices[i - 1]) for i in range(-9, 0))
        price_efficiency = net_move / max(total_move, 0.0001)
    else:
        price_efficiency = 0.0

    # Orderbook depth (approximate from bid/ask prices)
    ob_bid_depth = bid_prices[-1] * 100 if bid_prices else 0.0  # proxy
    ob_ask_depth = ask_prices[-1] * 100 if ask_prices else 0.0
    ob_total = ob_bid_depth + ob_ask_depth
    ob_imbalance = (ob_bid_depth - ob_ask_depth) / ob_total if ob_total > 0 else 0.0

    # Velocity
    price_velocity = price_change_5m / 5.0 if len(prices) >= 6 else 0.0

    # Spread percentage
    spread_pct = current_spread / max(current_price, 0.01)

    # Build the MarketFeatures object
    feat = MarketFeatures(
        ticker="historical",
        timestamp=now_fake,
        midpoint=current_price,
        spread=current_spread,
        spread_pct=spread_pct,
        last_price=current_price,
        price_change_1m=price_change_1m,
        price_change_5m=price_change_5m,
        price_change_15m=price_change_15m,
        price_velocity=price_velocity,
        sma_5=sma_5,
        sma_20=sma_20,
        ema_12=ema_12,
        ema_26=ema_26,
        macd=macd,
        signal_line=signal_line,
        rsi_14=rsi_14,
        momentum_10=momentum_10,
        volume=current_volume,
        volume_ma_5=vol_ma_5,
        volume_ratio=volume_ratio,
        open_interest=current_oi,
        oi_change=oi_change,
        book_imbalance=ob_imbalance,
        hours_to_expiry=hours_to_expiry,
        time_decay_factor=time_decay_factor,
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        hour_sin=hour_sin,
        hour_cos=hour_cos,
        dow_sin=dow_sin,
        dow_cos=dow_cos,
        event_prob_sum=1.0,
        implied_prob=implied_prob,
        prob_distance_from_50=prob_distance,
        extreme_prob=extreme_prob,
        convergence_rate=convergence_rate,
        normalized_time=normalized_time,
        price_time_signal=price_time_signal,
        info_rate=info_rate,
        spread_time_ratio=spread_time_ratio,
        log_odds=log_odds,
        overround=overround,
        price_acceleration=price_acceleration,
        volatility_5=volatility_5,
        volatility_20=volatility_20,
        volatility_ratio=volatility_ratio,
        bollinger_pct=bollinger_pct,
        price_zscore=price_zscore,
        price_bin=price_bin,
        kelly_edge=kelly_edge,
        vwap_deviation=vwap_deviation,
        obv_signal=obv_signal,
        spread_velocity=spread_velocity,
        price_range=price_range,
        hurst_proxy=hurst_proxy,
        settlement_confidence=settlement_confidence,
        time_urgency=time_urgency,
        volume_momentum=volume_momentum,
        oi_velocity=oi_velocity,
        volume_price_trend=volume_price_trend,
        rsi_divergence=rsi_divergence,
        macd_histogram=macd_histogram,
        mean_reversion_signal=mean_reversion_signal,
        smart_money_flow=smart_money_flow,
        edge_decay=edge_decay,
        price_efficiency=price_efficiency,
        ob_bid_depth=ob_bid_depth,
        ob_ask_depth=ob_ask_depth,
        ob_imbalance=ob_imbalance,
    )
    return feat


def build_training_dataset(
    db_path: str | Path | None = None,
    series: list[str] | None = None,
    time_slices: list[float] | None = None,
    min_candles: int = 10,
    max_markets: int = 0,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """
    Build (X, y, metadata) training arrays from historical data.

    Args:
        db_path: Path to historical.db (default: data/historical.db).
        series: Series tickers to include (default: all with candles).
        time_slices: Fractions of remaining time at which to compute features.
        min_candles: Minimum candles required per market.
        max_markets: Maximum markets to process (0=unlimited).

    Returns:
        X: Feature matrix (n_samples, n_features).
        y: Labels (1.0=YES, 0.0=NO).
        meta: List of dicts with ticker, slice info, etc.
    """
    from app.frankenstein.historical import HistoricalHarvester

    slices = time_slices or DEFAULT_TIME_SLICES
    path = Path(db_path) if db_path else None

    # Get markets with candle data
    markets = HistoricalHarvester.get_markets_with_candles(
        db_path=path, series=series, min_candles=min_candles,
    )

    if max_markets:
        markets = markets[:max_markets]

    log.info("building_training_data",
             markets=len(markets), slices=len(slices))

    all_features: list[np.ndarray] = []
    all_labels: list[float] = []
    all_meta: list[dict[str, Any]] = []

    conn = HistoricalHarvester.get_db(path)

    try:
        for i, mkt in enumerate(markets):
            ticker = mkt["ticker"]
            result = mkt["result"]
            label = 1.0 if result == "yes" else 0.0

            # Fetch candles
            candle_rows = conn.execute("""
                SELECT * FROM candles
                WHERE market_ticker = ?
                ORDER BY end_period_ts ASC
            """, (ticker,)).fetchall()

            if len(candle_rows) < min_candles:
                continue

            candles = [dict(row) for row in candle_rows]
            total_candles = len(candles)

            # Compute total duration from first to last candle
            first_ts = candles[0].get("end_period_ts", 0)
            last_ts = candles[-1].get("end_period_ts", 0)
            total_duration_s = max(last_ts - first_ts, 60)
            total_duration_h = total_duration_s / 3600.0

            # Generate features at each time slice
            for frac_remaining in slices:
                # slice_idx = index in candles where we "cut"
                # frac_remaining=0.50 means we use the first 50% of candles
                slice_idx = int(total_candles * (1.0 - frac_remaining))
                if slice_idx < MIN_CANDLES_PER_SLICE:
                    continue
                if slice_idx >= total_candles:
                    slice_idx = total_candles - 1

                candle_slice = candles[:slice_idx]
                hours_remaining = frac_remaining * total_duration_h

                feat = compute_features_from_candles(
                    candle_slice,
                    slice_idx,
                    total_candles,
                    hours_remaining,
                    total_duration_h,
                    result,
                )

                if feat is None:
                    continue

                arr = feat.to_array()
                # Validate: skip if too many NaN/inf
                if np.isnan(arr).sum() > 5 or np.isinf(arr).any():
                    continue
                # Replace any remaining NaN with 0
                arr = np.nan_to_num(arr, nan=0.0, posinf=1.0, neginf=-1.0)

                all_features.append(arr)
                all_labels.append(label)
                all_meta.append({
                    "ticker": ticker,
                    "series": mkt.get("series_ticker", ""),
                    "result": result,
                    "frac_remaining": frac_remaining,
                    "hours_remaining": hours_remaining,
                    "candles_used": len(candle_slice),
                    "total_candles": total_candles,
                })

            if (i + 1) % 500 == 0:
                log.info("feature_progress",
                         markets=i + 1, samples=len(all_features))
    finally:
        conn.close()

    if not all_features:
        log.warning("no_features_computed")
        return np.array([]), np.array([]), []

    X = np.array(all_features, dtype=np.float32)
    y = np.array(all_labels, dtype=np.float32)

    log.info("training_data_built",
             samples=len(X),
             features=X.shape[1],
             markets=len(markets),
             positive_rate=f"{y.mean():.3f}")

    return X, y, all_meta


def compute_edge_distribution(
    db_path: str | Path | None = None,
    series: list[str] | None = None,
) -> dict[str, dict[str, float]]:
    """
    Phase 13: Compute data-driven edge caps from historical distributions.

    For each series/category, compute the 95th percentile of price changes.
    Edges above this are almost certainly model errors, not real opportunities.

    Returns:
        {category: {"p95_edge": float, "mean_edge": float, "max_real_edge": float}}
    """
    from app.frankenstein.historical import HistoricalHarvester

    conn = HistoricalHarvester.get_db(db_path)
    try:
        # Get all markets with candles, grouped by series
        series_data: dict[str, list[float]] = {}
        rows = conn.execute("""
            SELECT m.series_ticker, c.price_close, c.bid_close, c.ask_close
            FROM markets m
            JOIN candles c ON c.market_ticker = m.ticker
            WHERE m.result IS NOT NULL
            ORDER BY m.series_ticker, c.end_period_ts
        """).fetchall()

        prev_prices: dict[str, float] = {}
        for row in rows:
            series_t = row[0]
            bid = float(row[2] or 0)
            ask = float(row[3] or 0)
            price = float(row[1] or 0)
            if bid > 1.5:
                bid /= 100.0
            if ask > 1.5:
                ask /= 100.0
            if price > 1.5:
                price /= 100.0
            mid = (bid + ask) / 2.0 if bid > 0 and ask > 0 else price
            if mid <= 0:
                continue

            key = f"{series_t}_{row[0]}"  # unique per market
            if key in prev_prices:
                change = abs(mid - prev_prices[key])
                series_data.setdefault(series_t, []).append(change)
            prev_prices[key] = mid

        result: dict[str, dict[str, float]] = {}
        for series_t, changes in series_data.items():
            if len(changes) < 100:
                continue
            arr = np.array(changes)
            result[series_t] = {
                "p95_edge": float(np.percentile(arr, 95)),
                "mean_edge": float(np.mean(arr)),
                "max_real_edge": float(np.percentile(arr, 99)),
                "samples": len(changes),
            }

        return result
    finally:
        conn.close()


# ── Standalone ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("Building training dataset from historical data...")
    X, y, meta = build_training_dataset()
    if len(X) > 0:
        print(f"✅ Dataset built: {X.shape[0]} samples × {X.shape[1]} features")
        print(f"   Positive rate (YES): {y.mean():.3f}")
        print(f"   Unique markets: {len(set(m['ticker'] for m in meta))}")

        # Feature statistics
        print(f"\nFeature statistics:")
        names = MarketFeatures.feature_names()
        for j, name in enumerate(names):
            col = X[:, j]
            nonzero = (col != 0.0).sum()
            print(f"   {name:<30} nonzero={nonzero:>6}/{len(col)}  "
                  f"mean={col.mean():>8.4f}  std={col.std():>8.4f}")
    else:
        print("❌ No training data generated. Run the harvester first.")
        sys.exit(1)
