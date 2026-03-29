"""
Frankenstein — Walk-Forward Backtesting Engine (Phase 18).

Simulates Frankenstein's trading logic against historical data to:
  1. Validate model profitability BEFORE live deployment
  2. Compute strategy parameters from data (not guesses)
  3. Gate model versions — only deploy if backtest is profitable

The backtest respects:
  - Kalshi fee model: maker (0¢) or taker (7¢/side)
  - MAKER MODE by default: place at bid, hold to settlement, 0¢ fees
  - Realistic spread costs (from historical bid/ask)
  - Time-ordered walk-forward (no look-ahead bias)
  - Position sizing via Kelly criterion
  - Edge and confidence thresholds

Usage:
    from app.frankenstein.backtest import run_backtest
    results = run_backtest()
"""

from __future__ import annotations

import math
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.ai.features import MarketFeatures
from app.logging_config import get_logger

log = get_logger("frankenstein.backtest")

TAKER_FEE_CENTS = 7
ROUND_TRIP_FEE_CENTS = 14
MAKER_FEE_CENTS = 0       # Kalshi maker orders are FREE
USE_MAKER_ORDERS = True    # Match brain.py setting
STARTING_BALANCE_CENTS = 1_000_000  # $10,000


@dataclass
class BacktestTrade:
    """A single simulated trade."""
    ticker: str
    series: str
    side: str             # "yes" or "no"
    predicted_prob: float
    market_price: float
    edge: float
    price_cents: int
    count: int
    result: str           # "yes" or "no" (actual outcome)
    pnl_cents: int = 0
    fees_cents: int = 0
    correct: bool = False


@dataclass
class BacktestResult:
    """Results of a walk-forward backtest."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl_cents: int = 0
    total_fees_cents: int = 0
    gross_pnl_cents: int = 0
    max_drawdown_cents: int = 0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    avg_pnl_per_trade: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    kelly_optimal_fraction: float = 0.0
    trades: list[BacktestTrade] = field(default_factory=list)

    # By-series breakdown
    series_breakdown: dict[str, dict[str, Any]] = field(default_factory=dict)

    # Strategy parameter recommendations
    recommended_min_edge: float = 0.0
    recommended_price_floor: float = 0.0
    recommended_daily_cap: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": f"{self.win_rate:.1%}",
            "total_pnl": f"${self.total_pnl_cents / 100:.2f}",
            "total_fees": f"${self.total_fees_cents / 100:.2f}",
            "gross_pnl": f"${self.gross_pnl_cents / 100:.2f}",
            "avg_pnl_per_trade": f"${self.avg_pnl_per_trade / 100:.2f}",
            "max_drawdown": f"${self.max_drawdown_cents / 100:.2f}",
            "max_drawdown_pct": f"{self.max_drawdown_pct:.1%}",
            "sharpe_ratio": f"{self.sharpe_ratio:.2f}",
            "profit_factor": f"{self.profit_factor:.2f}",
            "recommended_min_edge": f"{self.recommended_min_edge:.3f}",
            "recommended_price_floor": f"{self.recommended_price_floor:.2f}",
            "recommended_daily_cap": self.recommended_daily_cap,
            "series_breakdown": self.series_breakdown,
        }


def run_backtest(
    model_path: str | Path | None = None,
    db_path: str | Path | None = None,
    series: list[str] | None = None,
    min_edge: float = 0.03,     # lowered: maker fees are 0¢
    min_price: float = 0.25,    # lowered: no fee trap with 0¢ fees
    max_price: float = 0.80,
    max_spread: float = 0.10,
    kelly_fraction: float = 0.15,
    max_daily_trades: int = 20,
    max_contracts: int = 3,
) -> BacktestResult:
    """
    Run a walk-forward backtest using the pre-trained model against
    historical data.

    The backtest uses ONLY data available up to each time slice —
    no future information leaks.

    Args:
        model_path: Path to pre-trained model pickle.
        db_path: Path to historical.db.
        series: Series tickers to backtest on.
        min_edge: Minimum |edge| to trade.
        min_price: Minimum midpoint price.
        max_price: Maximum midpoint price.
        max_spread: Maximum spread allowed.
        kelly_fraction: Fractional Kelly for position sizing.
        max_daily_trades: Max trades per simulated day.
        max_contracts: Max contracts per trade.

    Returns:
        BacktestResult with full metrics and trade log.
    """
    import xgboost as xgb
    from app.frankenstein.historical_features import (
        build_training_dataset,
        compute_features_from_candles,
    )
    from app.frankenstein.historical import HistoricalHarvester
    from app.frankenstein.pretrained import load_pretrained_model, PRETRAINED_PATH

    # Load model
    m_path = Path(model_path) if model_path else PRETRAINED_PATH
    loaded = load_pretrained_model(m_path)
    if not loaded:
        log.error("no_model_for_backtest")
        return BacktestResult()
    xgb_model, calibration, meta = loaded
    feature_names = MarketFeatures.feature_names()

    # Get markets with candles
    markets = HistoricalHarvester.get_markets_with_candles(
        db_path=db_path, series=series, min_candles=10,
    )

    log.info("backtest_start",
             markets=len(markets), min_edge=min_edge,
             price_range=f"{min_price:.0%}-{max_price:.0%}")

    # Use last 20% of markets as backtest set (not used in training)
    n_skip = int(len(markets) * 0.80)
    backtest_markets = markets[n_skip:]

    if not backtest_markets:
        log.warning("no_backtest_markets")
        return BacktestResult()

    conn = HistoricalHarvester.get_db(db_path)
    result = BacktestResult()
    balance_cents = STARTING_BALANCE_CENTS
    peak_balance = balance_cents
    daily_trades: dict[int, int] = {}  # day_index → count

    try:
        for mkt in backtest_markets:
            ticker = mkt["ticker"]
            mkt_result = mkt["result"]
            series_t = mkt.get("series_ticker", "unknown")

            # Fetch candles
            candle_rows = conn.execute("""
                SELECT * FROM candles
                WHERE market_ticker = ?
                ORDER BY end_period_ts ASC
            """, (ticker,)).fetchall()
            candles = [dict(row) for row in candle_rows]
            if len(candles) < 10:
                continue

            total_candles = len(candles)
            first_ts = candles[0].get("end_period_ts", 0)
            last_ts = candles[-1].get("end_period_ts", 0)
            total_duration_h = max((last_ts - first_ts) / 3600.0, 0.25)

            # Evaluate at 30% time remaining
            frac = 0.30
            slice_idx = int(total_candles * (1.0 - frac))
            if slice_idx < 5:
                continue

            candle_slice = candles[:slice_idx]
            hours_remaining = frac * total_duration_h

            feat = compute_features_from_candles(
                candle_slice, slice_idx, total_candles,
                hours_remaining, total_duration_h, mkt_result,
            )
            if feat is None:
                continue

            # Apply price filter
            mid = feat.midpoint
            if mid < min_price or mid > max_price:
                continue

            # Apply spread filter
            if feat.spread > max_spread:
                continue

            # Predict
            X_single = feat.to_array().reshape(1, -1)
            X_single = np.nan_to_num(X_single, nan=0.0)
            dmatrix = xgb.DMatrix(X_single, feature_names=feature_names)
            prob_yes = float(xgb_model.predict(dmatrix)[0])

            # Calibrate
            if calibration.is_ready:
                prob_yes = calibration.calibrate(prob_yes)

            # Edge
            edge = prob_yes - mid
            side = "yes" if edge > 0 else "no"
            abs_edge = abs(edge)

            if abs_edge < min_edge:
                continue

            # Fee + EV gate
            # MAKER MODE: entry at bid (not ask), fees are 0¢.
            # Hold to settlement: no sell fee.
            # TAKER MODE: entry at ask, fees are 7¢/side.
            if USE_MAKER_ORDERS:
                # Maker enters at the BID — better price than taker
                if side == "yes":
                    entry_price = min(0.99, max(0.01, mid - feat.spread / 2))
                    p_win = prob_yes
                else:
                    entry_price = min(0.99, max(0.01, (1.0 - mid) - feat.spread / 2))
                    p_win = 1.0 - prob_yes
                buy_fee_dollars = 0.0  # maker = free
                sell_fee_dollars = 0.0  # hold to settlement = no sell
            else:
                # Taker enters at the ASK
                if side == "yes":
                    entry_price = min(0.99, max(0.01, mid + feat.spread / 2))
                    p_win = prob_yes
                else:
                    entry_price = min(0.99, max(0.01, (1.0 - mid) + feat.spread / 2))
                    p_win = 1.0 - prob_yes
                buy_fee_dollars = TAKER_FEE_CENTS / 100.0
                sell_fee_dollars = TAKER_FEE_CENTS / 100.0

            ev_per_contract = (
                p_win * (1.0 - entry_price - buy_fee_dollars - sell_fee_dollars)
                + (1.0 - p_win) * (-entry_price - buy_fee_dollars)
            )
            if ev_per_contract <= 0:
                continue

            # Daily trade cap
            day_idx = first_ts // 86400
            if daily_trades.get(day_idx, 0) >= max_daily_trades:
                continue
            daily_trades[day_idx] = daily_trades.get(day_idx, 0) + 1

            # Kelly sizing
            if side == "yes":
                p = prob_yes
                c = entry_price
            else:
                p = 1.0 - prob_yes
                c = entry_price

            if USE_MAKER_ORDERS:
                fee = 0.0
            else:
                fee = TAKER_FEE_CENTS / 100.0
            real_cost = c + fee
            net_win = (1.0 - fee) - c
            if p <= real_cost or net_win <= 0:
                continue
            kelly = (p - real_cost) / net_win
            adjusted_kelly = kelly * kelly_fraction
            count = max(1, min(int(adjusted_kelly * 10), max_contracts))

            # Simulate execution
            price_cents = int(round(entry_price * 100))
            if USE_MAKER_ORDERS:
                buy_fee = 0
                sell_fee = 0
            else:
                buy_fee = TAKER_FEE_CENTS * count
                sell_fee = TAKER_FEE_CENTS * count
            total_fee = buy_fee + sell_fee
            buy_cost = price_cents * count

            correct = (side == mkt_result)
            if correct:
                gross_pnl = (100 * count) - buy_cost  # win payout minus cost
                net_pnl = gross_pnl - total_fee
            else:
                gross_pnl = -buy_cost
                net_pnl = gross_pnl - buy_fee  # only pay buy fee on loss (no sell)

            trade = BacktestTrade(
                ticker=ticker,
                series=series_t,
                side=side,
                predicted_prob=prob_yes,
                market_price=mid,
                edge=abs_edge,
                price_cents=price_cents,
                count=count,
                result=mkt_result,
                pnl_cents=net_pnl,
                fees_cents=total_fee if correct else buy_fee,
                correct=correct,
            )
            result.trades.append(trade)
            result.total_trades += 1

            if correct:
                result.wins += 1
                result.gross_pnl_cents += gross_pnl
            else:
                result.losses += 1
                result.gross_pnl_cents += gross_pnl

            result.total_pnl_cents += net_pnl
            result.total_fees_cents += trade.fees_cents
            balance_cents += net_pnl

            # Drawdown tracking
            peak_balance = max(peak_balance, balance_cents)
            drawdown = peak_balance - balance_cents
            if drawdown > result.max_drawdown_cents:
                result.max_drawdown_cents = drawdown
                result.max_drawdown_pct = drawdown / max(peak_balance, 1)

            # Series breakdown
            if series_t not in result.series_breakdown:
                result.series_breakdown[series_t] = {
                    "trades": 0, "wins": 0, "losses": 0, "pnl_cents": 0
                }
            result.series_breakdown[series_t]["trades"] += 1
            if correct:
                result.series_breakdown[series_t]["wins"] += 1
            else:
                result.series_breakdown[series_t]["losses"] += 1
            result.series_breakdown[series_t]["pnl_cents"] += net_pnl

    finally:
        conn.close()

    # Compute aggregate metrics
    if result.total_trades > 0:
        result.win_rate = result.wins / result.total_trades
        result.avg_pnl_per_trade = result.total_pnl_cents / result.total_trades

        # Sharpe ratio (daily)
        pnls = [t.pnl_cents for t in result.trades]
        if len(pnls) > 1:
            pnl_std = float(np.std(pnls))
            if pnl_std > 0:
                result.sharpe_ratio = (float(np.mean(pnls)) / pnl_std) * math.sqrt(252)

        # Profit factor
        gross_wins = sum(t.pnl_cents for t in result.trades if t.pnl_cents > 0)
        gross_losses = abs(sum(t.pnl_cents for t in result.trades if t.pnl_cents < 0))
        result.profit_factor = gross_wins / max(gross_losses, 1)

    # Strategy recommendations from backtest data
    if result.trades:
        winning_edges = [t.edge for t in result.trades if t.correct]
        losing_edges = [t.edge for t in result.trades if not t.correct]
        if winning_edges:
            result.recommended_min_edge = float(np.percentile(winning_edges, 25))
        winning_prices = [t.market_price for t in result.trades if t.correct]
        if winning_prices:
            result.recommended_price_floor = float(np.percentile(winning_prices, 10))
        # Cap recommendation: trades per day where we're profitable
        if result.win_rate > 0.5:
            result.recommended_daily_cap = min(20, max(5, int(result.total_trades / max(len(daily_trades), 1))))
        else:
            result.recommended_daily_cap = 10

    log.info("backtest_complete", **{
        k: v for k, v in result.summary().items()
        if k != "series_breakdown"
    })

    return result


# ── Model version gate ────────────────────────────────────────────────

def gate_model_deployment(
    model_path: str | Path,
    min_win_rate: float = 0.52,
    min_profit_factor: float = 1.1,
    max_drawdown_pct: float = 0.15,
    min_trades: int = 50,
    **backtest_kwargs: Any,
) -> tuple[bool, dict[str, Any]]:
    """
    Phase 19: Gate a model version before live deployment.

    Runs backtest and checks if it meets minimum profitability thresholds.

    Returns:
        (should_deploy, backtest_summary)
    """
    result = run_backtest(model_path=model_path, **backtest_kwargs)

    checks = {
        "enough_trades": result.total_trades >= min_trades,
        "profitable": result.total_pnl_cents > 0,
        "win_rate": result.win_rate >= min_win_rate,
        "profit_factor": result.profit_factor >= min_profit_factor,
        "drawdown": result.max_drawdown_pct <= max_drawdown_pct,
    }

    should_deploy = all(checks.values())

    summary = result.summary()
    summary["gate_checks"] = checks
    summary["gate_passed"] = should_deploy

    if should_deploy:
        log.info("✅ MODEL GATE PASSED", **checks)
    else:
        failed = [k for k, v in checks.items() if not v]
        log.warning("❌ MODEL GATE FAILED", failed=failed, **checks)

    return should_deploy, summary


# ── Standalone ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Frankenstein Backtest Engine")
    parser.add_argument("--model", default=None, help="Model path")
    parser.add_argument("--db", default=None, help="Historical database path")
    parser.add_argument("--series", nargs="+", default=None, help="Series")
    parser.add_argument("--min-edge", type=float, default=0.05, help="Min edge")
    parser.add_argument("--min-price", type=float, default=0.30, help="Min price")
    parser.add_argument("--max-price", type=float, default=0.80, help="Max price")
    parser.add_argument("--kelly", type=float, default=0.15, help="Kelly fraction")
    parser.add_argument("--gate", action="store_true", help="Run deployment gate")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()

    if args.gate:
        passed, summary = gate_model_deployment(
            model_path=args.model or "",
            min_edge=args.min_edge,
            min_price=args.min_price,
            max_price=args.max_price,
            kelly_fraction=args.kelly,
        )
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"\n{'✅ GATE PASSED' if passed else '❌ GATE FAILED'}")
            for k, v in summary.items():
                if k != "series_breakdown":
                    print(f"  {k}: {v}")
    else:
        result = run_backtest(
            model_path=args.model,
            db_path=args.db,
            series=args.series,
            min_edge=args.min_edge,
            min_price=args.min_price,
            max_price=args.max_price,
            kelly_fraction=args.kelly,
        )
        summary = result.summary()
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"\n📊 Backtest Results:")
            for k, v in summary.items():
                if k == "series_breakdown":
                    print(f"\n  Series Breakdown:")
                    for s, data in v.items():
                        wr = data['wins'] / max(data['trades'], 1)
                        print(f"    {s}: {data['trades']} trades, "
                              f"{wr:.0%} WR, ${data['pnl_cents']/100:.2f}")
                else:
                    print(f"  {k}: {v}")
