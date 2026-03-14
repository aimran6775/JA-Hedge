"""
Frankenstein — Bootstrap Training Data Generator.

Solves the cold-start problem: Frankenstein needs resolved trades
to train its model, but can't make trades without a trained model.

This module fetches recently settled markets from Kalshi, computes
features from their pre-settlement state, and injects synthetic
training records into Frankenstein's memory. Once enough data
accumulates (≥50 samples), the learner can train its first model.

Data sources:
  1. Kalshi API: settled markets with known outcomes (yes/no)
  2. Market cache: active markets used to synthesize "what if" features
  3. Historical prices on settled markets: last_price ≈ final probability
"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.ai.models import Prediction
from app.frankenstein.memory import TradeMemory, TradeOutcome
from app.kalshi.api import KalshiAPI
from app.kalshi.models import Market, MarketStatus
from app.logging_config import get_logger
from app.pipeline import market_cache

log = get_logger("frankenstein.bootstrap")


def _features_from_market(m: Market, *, jitter: bool = True) -> MarketFeatures:
    """
    Compute a realistic feature vector from a market snapshot.

    For settled markets the bid/ask are gone, but last_price is set.
    For active markets we have full orderbook data.
    We add small random jitter when building bootstrap data so the model
    doesn't overfit to exact feature values.
    """
    now = datetime.now(timezone.utc)

    # Extract prices — handle both Decimal and None
    yes_bid = float(m.yes_bid) if m.yes_bid is not None else 0.0
    yes_ask = float(m.yes_ask) if m.yes_ask is not None else 0.0
    no_bid = float(m.no_bid) if m.no_bid is not None else 0.0
    no_ask = float(m.no_ask) if m.no_ask is not None else 0.0
    last = float(m.last_price) if m.last_price is not None else 0.0
    vol = float(m.volume) if m.volume is not None else 0.0
    vol_int = m.volume_int or 0
    oi = float(m.open_interest) if m.open_interest is not None else 0.0

    # For settled markets, approximate bid/ask from last price
    if yes_bid == 0 and yes_ask == 0 and last > 0:
        yes_bid = max(0.01, last - 0.02)
        yes_ask = min(0.99, last + 0.02)
        no_bid = max(0.01, 1.0 - yes_ask)
        no_ask = min(0.99, 1.0 - yes_bid)

    mid = (yes_bid + yes_ask) / 2 if (yes_bid + yes_ask) > 0 else last
    spread = yes_ask - yes_bid if yes_ask > yes_bid else 0.04
    spread_pct = spread / mid if mid > 0 else 0.0

    # Time to expiry
    hours_to_expiry = 0.0
    if m.expiration_time:
        delta = (m.expiration_time - now).total_seconds() / 3600
        hours_to_expiry = max(delta, 0.0)
    elif m.close_time:
        delta = (m.close_time - now).total_seconds() / 3600
        hours_to_expiry = max(delta, 0.0)

    # For settled markets, simulate time-to-expiry at trade time
    # (they were traded hours/days before settlement)
    if hours_to_expiry <= 0:
        hours_to_expiry = random.uniform(2.0, 72.0) if jitter else 24.0

    time_decay = 1.0 / math.sqrt(max(hours_to_expiry, 0.1))
    hour_of_day = now.hour
    day_of_week = now.weekday()

    # Implied probability features
    implied_prob = mid if mid > 0 else 0.5
    prob_dist_50 = abs(implied_prob - 0.5)
    extreme = implied_prob < 0.1 or implied_prob > 0.9

    # Log-odds
    p_clamped = max(0.01, min(0.99, implied_prob))
    log_odds = math.log(p_clamped / (1 - p_clamped))

    # Overround
    overround = (yes_ask + no_ask) - 1.0 if yes_ask > 0 and no_ask > 0 else 0.04

    # Book imbalance (bid depth ratio)
    total_depth = yes_bid + (1.0 - yes_ask) if yes_ask > 0 else 1.0
    book_imbalance = (yes_bid - (1.0 - yes_ask)) / total_depth if total_depth > 0 else 0.0

    # Normalized time (0 = just opened, 1 = at expiry)
    if m.open_time and hours_to_expiry > 0:
        total_life = (m.expiration_time - m.open_time).total_seconds() / 3600 if m.expiration_time and m.open_time else 168.0
        normalized_time = max(0.0, min(1.0, 1.0 - hours_to_expiry / max(total_life, 1.0)))
    else:
        normalized_time = random.uniform(0.3, 0.95) if jitter else 0.7

    # Price-time signal
    price_time_signal = prob_dist_50 * normalized_time

    # Spread-time ratio
    spread_time_ratio = spread / max(hours_to_expiry, 0.1)

    # Jitter: add small noise to avoid overfitting to exact values
    def _j(v: float, scale: float = 0.02) -> float:
        if jitter:
            return v + random.gauss(0, scale * max(abs(v), 0.01))
        return v

    features = MarketFeatures(
        ticker=m.ticker,
        timestamp=now,
        midpoint=_j(mid),
        spread=_j(spread, 0.01),
        spread_pct=_j(spread_pct, 0.01),
        last_price=_j(last),
        price_change_1m=_j(0.0, 0.005),
        price_change_5m=_j(0.0, 0.01),
        price_change_15m=_j(0.0, 0.015),
        price_velocity=_j(0.0, 0.005),
        sma_5=_j(mid, 0.01),
        sma_20=_j(mid, 0.02),
        ema_12=_j(mid, 0.01),
        ema_26=_j(mid, 0.02),
        macd=_j(0.0, 0.005),
        signal_line=_j(0.0, 0.005),
        rsi_14=_j(50.0 + (mid - 0.5) * 20, 3.0),
        momentum_10=_j(0.0, 0.01),
        volume=_j(vol + vol_int, 5.0),
        volume_ma_5=_j(vol + vol_int, 5.0) * 0.9,
        volume_ratio=_j(1.0, 0.15),
        open_interest=_j(oi, 3.0),
        oi_change=_j(0.0, 1.0),
        book_imbalance=_j(book_imbalance, 0.05),
        hours_to_expiry=hours_to_expiry,
        time_decay_factor=time_decay,
        hour_of_day=hour_of_day,
        day_of_week=day_of_week,
        is_market_hours=True,
        implied_prob=_j(implied_prob),
        prob_distance_from_50=prob_dist_50,
        extreme_prob=extreme,
        convergence_rate=_j(0.0, 0.01),
        normalized_time=normalized_time,
        price_time_signal=price_time_signal,
        info_rate=_j(0.0, 0.005),
        spread_time_ratio=spread_time_ratio,
        log_odds=log_odds,
        overround=overround,
        price_acceleration=_j(0.0, 0.005),
        # Phase 4: advanced statistical features
        volatility_5=_j(0.01, 0.005),
        volatility_20=_j(0.008, 0.003),
        volatility_ratio=_j(1.2, 0.3),
        bollinger_pct=_j(0.5, 0.15),
        price_zscore=_j(0.0, 0.5),
        price_bin=round(mid * 10) / 10,
        kelly_edge=_j(abs(mid - 0.5) * 2 * time_decay * 0.1, 0.005),
        vwap_deviation=_j(0.0, 0.01),
        obv_signal=_j(0.0, 0.2),
        spread_velocity=_j(0.0, 0.005),
        price_range=_j(0.05, 0.02),
        hurst_proxy=_j(0.5, 0.1),
        settlement_confidence=2 * abs(mid - 0.5),
        time_urgency=math.exp(-hours_to_expiry / 24.0) if hours_to_expiry >= 0 else 0.0,
        volume_momentum=_j(0.0, 0.01),
        # Phase 5: elite edge features
        oi_velocity=_j(0.0, 0.5),
        volume_price_trend=_j(0.0, 0.3),
        rsi_divergence=_j(0.0, 0.02),
        macd_histogram=_j(0.0, 0.005),
        mean_reversion_signal=_j(0.0, 0.2),
        smart_money_flow=_j(0.0, 0.3),
        edge_decay=_j(0.0, 0.02),
        price_efficiency=_j(0.3, 0.15),
    )
    return features


async def bootstrap_from_settled_markets(
    api: KalshiAPI,
    memory: TradeMemory,
    *,
    max_markets: int = 1000,
    min_target: int = 300,
) -> dict[str, Any]:
    """
    Fetch settled markets from Kalshi and inject synthetic training records.

    This is the primary cold-start strategy: settled markets have known
    outcomes (yes/no), and we can reconstruct approximate features from
    their final price state to create labeled training data.

    Returns summary stats.
    """
    log.info("bootstrap_starting", target=min_target, max_fetch=max_markets)
    stats = {
        "fetched": 0,
        "usable": 0,
        "injected": 0,
        "skipped_void": 0,
        "skipped_no_result": 0,
        "skipped_scalar": 0,
        "errors": 0,
    }

    try:
        # Fetch settled markets from Kalshi API
        settled_markets = await _fetch_settled_markets(api, max_markets)
        stats["fetched"] = len(settled_markets)
    except Exception as e:
        log.error("bootstrap_fetch_failed", error=str(e))
        stats["errors"] += 1
        return stats

    for mkt, result_str in settled_markets:
        if stats["injected"] >= min_target:
            break

        if result_str in ("void",):
            stats["skipped_void"] += 1
            continue
        if result_str not in ("yes", "no"):
            stats["skipped_no_result"] += 1
            continue

        try:
            features = _features_from_market(mkt, jitter=True)

            # Create a synthetic prediction that "would have been made"
            # The model learns from outcomes, not from our mock predictions
            prob = float(mkt.last_price) if mkt.last_price else 0.5
            side = "yes" if prob >= 0.5 else "no"

            prediction = Prediction(
                predicted_prob=prob,
                confidence=abs(prob - 0.5) * 2,  # higher for extreme prices
                side=side,
                edge=abs(prob - 0.5) * 0.1,
                model_name="bootstrap_v0",
            )

            # Record trade
            price_cents = max(1, min(99, int(prob * 100)))
            record = memory.record_trade(
                ticker=mkt.ticker,
                prediction=prediction,
                features=features,
                action="buy",
                count=1,
                price_cents=price_cents,
                order_id=f"bootstrap-{mkt.ticker}",
                model_version="bootstrap_v0",
            )

            # Immediately resolve with known outcome
            correct = side == result_str
            if correct:
                pnl_cents = 100 - price_cents  # win: receive $1 minus cost
            else:
                pnl_cents = -price_cents  # loss: lose cost

            memory.resolve_trade(
                trade_id=record.trade_id,
                outcome=TradeOutcome.WIN if correct else TradeOutcome.LOSS,
                pnl_cents=pnl_cents,
                market_result=result_str,
            )

            stats["injected"] += 1
            stats["usable"] += 1

        except Exception as e:
            log.debug("bootstrap_record_error", ticker=mkt.ticker, error=str(e))
            stats["errors"] += 1

    log.info(
        "bootstrap_complete",
        injected=stats["injected"],
        fetched=stats["fetched"],
        usable=stats["usable"],
    )
    return stats


async def bootstrap_from_active_markets(
    memory: TradeMemory,
    *,
    count: int = 500,
) -> dict[str, Any]:
    """
    Fallback bootstrap: generate training data from ACTIVE markets.

    Uses current market prices as ground truth probabilities. Markets
    priced at 90¢+ are labeled YES, markets at 10¢ or below are NO,
    and mid-range markets get probabilistic labels.

    This is noisier than settled-market data but works when the API
    can't return settled markets (e.g., demo mode).
    """
    log.info("bootstrap_from_active_starting", target=count)
    stats = {"scanned": 0, "injected": 0, "skipped": 0, "errors": 0}

    markets = market_cache.get_active()
    if not markets:
        log.warning("bootstrap_active_no_markets")
        return stats

    # Shuffle to get variety
    random.shuffle(markets)

    for m in markets:
        if stats["injected"] >= count:
            break

        stats["scanned"] += 1

        # Need price data — handle Decimal carefully
        try:
            mid = float(m.midpoint) if m.midpoint is not None else None
        except (TypeError, ValueError):
            mid = None
        try:
            last = float(m.last_price) if m.last_price is not None else None
        except (TypeError, ValueError):
            last = None

        price = mid or last
        if price is None or price <= 0.01 or price >= 0.99:
            stats["skipped"] += 1
            continue

        # Volume is not critical for bootstrap data quality — skip the filter
        # (We want to learn from price patterns, not just liquid markets)

        try:
            features = _features_from_market(m, jitter=True)

            # Probabilistic labeling based on current price:
            # - Price 0.85+ → very likely YES → label YES ~85% of the time
            # - Price 0.15- → very likely NO  → label NO ~85% of the time
            # - Mid-range  → use price as P(YES), sample outcome
            result_str = "yes" if random.random() < price else "no"

            side = "yes" if price >= 0.5 else "no"
            prediction = Prediction(
                predicted_prob=price,
                confidence=abs(price - 0.5) * 2,
                side=side,
                edge=abs(price - 0.5) * 0.08,
                model_name="bootstrap_active_v0",
            )

            price_cents = max(1, min(99, int(price * 100)))
            record = memory.record_trade(
                ticker=m.ticker,
                prediction=prediction,
                features=features,
                action="buy",
                count=1,
                price_cents=price_cents,
                order_id=f"bootstrap-active-{m.ticker}",
                model_version="bootstrap_active_v0",
            )

            correct = side == result_str
            pnl_cents = (100 - price_cents) if correct else -price_cents

            memory.resolve_trade(
                trade_id=record.trade_id,
                outcome=TradeOutcome.WIN if correct else TradeOutcome.LOSS,
                pnl_cents=pnl_cents,
                market_result=result_str,
            )

            stats["injected"] += 1

        except Exception as e:
            log.debug("bootstrap_active_error", ticker=m.ticker, error=str(e))
            stats["errors"] += 1

    log.info("bootstrap_from_active_complete", **stats)
    return stats


async def _fetch_settled_markets(
    api: KalshiAPI,
    max_markets: int,
) -> list[tuple[Market, str]]:
    """
    Fetch settled markets with known outcomes from Kalshi.

    Returns list of (Market, result_string) tuples.
    """
    results: list[tuple[Market, str]] = []

    try:
        # Method 1: Get settled markets directly via API
        cursor = None
        fetched = 0
        while fetched < max_markets:
            batch_size = min(200, max_markets - fetched)
            markets, cursor = await api.markets.list_markets(
                status=MarketStatus.SETTLED,
                limit=batch_size,
                cursor=cursor,
            )
            if not markets:
                break

            for m in markets:
                # Kalshi returns 'result' field on settled markets
                result_str = (m.result or "").lower()

                # If no explicit result, infer from last_price:
                #   Settled at $1.00 → YES won, Settled at $0.00 → NO won
                if not result_str and m.last_price is not None:
                    lp = float(m.last_price)
                    if lp >= 0.95:
                        result_str = "yes"
                    elif lp <= 0.05:
                        result_str = "no"

                if result_str in ("yes", "no"):
                    results.append((m, result_str))

            fetched += len(markets)
            if not cursor:
                break

    except Exception as e:
        log.warning("settled_fetch_via_api_failed", error=str(e))

    # Method 2: If API didn't give enough, try settlements endpoint
    if len(results) < 50:
        try:
            settlements, _ = await api.portfolio.list_settlements(limit=200)
            for s in settlements:
                if s.market_result is not None:
                    result_str = s.market_result.value.lower()
                    if result_str in ("yes", "no"):
                        try:
                            mkt = await api.markets.get_market(s.ticker)
                            results.append((mkt, result_str))
                        except Exception:
                            pass
        except Exception as e:
            log.debug("settlements_fetch_failed", error=str(e))

    log.info("settled_markets_fetched", count=len(results))
    return results[:max_markets]
