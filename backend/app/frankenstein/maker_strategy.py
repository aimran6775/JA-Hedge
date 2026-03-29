"""
Frankenstein — Maker-Order Mispricing Strategy (Phase 21).

CORE INSIGHT (from data analysis on 17,598 markets):
  1. The 14¢ taker fee makes ALL strategies unprofitable on 15-min markets.
  2. Maker orders (0¢ fee) change the math completely.
  3. Kalshi crypto markets show systematic mispricings at certain price levels:
     - YES contracts at 35¢ resolve YES 41% (6% underpriced)
     - YES contracts at 60-70¢ resolve YES 63-76% (3-6% underpriced)
     - NO contracts at 45-55¢ resolve NO 54% (4% underpriced)
  4. By placing limit orders at the bid (maker), we capture these mispricings
     with 0 transaction costs.

STRATEGY:
  - Compute real-time mispricing score from historical calibration data
  - Place maker (limit) buy orders at the bid when mispricing > threshold
  - Hold to settlement (no early exit — exit strategies all lose money)
  - Use per-series calibration tables for price-bucket mispricings
  - Track fill rates and adjust placement to maintain edge

VALIDATED ON HOLDOUT:
  - 2,060 trades, 61.7% WR, +$61.61 (entry at 30% of market life)
  - 766 trades, 64.2% WR, +$29.18 (entry at 70% of market life)
  - Best segment: 55-70¢ YES buys at 70% time = 72.5% WR, +$21.80
"""

from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from app.logging_config import get_logger

log = get_logger("frankenstein.maker_strategy")

# Persist directory (same as pretrained model)
import os
_PERSIST_DIR = Path(os.environ.get("PERSIST_DIR",
    str(Path(__file__).resolve().parent.parent.parent / "data")))
CALIBRATION_PATH = _PERSIST_DIR / "models" / "calibration_table.json"


@dataclass
class MispricingSignal:
    """A detected mispricing opportunity."""
    ticker: str
    side: str  # "yes" or "no"
    market_price: float  # current midpoint
    limit_price_cents: int  # our bid (maker order price)
    expected_win_rate: float  # from calibration table
    breakeven_win_rate: float  # at 0¢ fee
    edge: float  # expected_win_rate - breakeven_win_rate
    confidence: float  # how much data backs this bucket
    time_fraction: float  # how far through market life (0=start, 1=end)
    entry_price_bucket: float  # the calibration bucket this falls into


@dataclass
class CalibrationBucket:
    """Empirical win rate for a price bucket."""
    price: float
    yes_wins: int = 0
    total: int = 0
    
    @property
    def win_rate(self) -> float:
        if self.total < 10:
            return self.price  # default to efficient market
        return self.yes_wins / self.total
    
    @property
    def calibration_error(self) -> float:
        """Positive = YES underpriced, Negative = YES overpriced."""
        return self.win_rate - self.price
    
    @property
    def confidence(self) -> float:
        """Confidence in the calibration (0 to 1)."""
        if self.total < 10:
            return 0.0
        # Binomial standard error
        se = math.sqrt(self.win_rate * (1 - self.win_rate) / self.total)
        # Confidence = 1 - relative_uncertainty
        return max(0.0, min(1.0, 1.0 - 2 * se / max(abs(self.calibration_error), 0.01)))


class MakerEdgeStrategy:
    """
    Mispricing-exploitation strategy using maker (limit) orders.
    
    The strategy maintains a calibration table that maps price buckets
    to empirical win rates. When a market's price falls in a bucket
    where the historical win rate significantly exceeds (or falls below)
    the market price, we place a limit order to exploit the mispricing.
    
    All orders are MAKER (limit at bid) to avoid the 14¢ taker fee
    that destroys any edge on 15-minute markets.
    """
    
    def __init__(self, min_edge: float = 0.03, min_confidence: float = 0.3,
                 min_bucket_samples: int = 50, bucket_size: float = 0.05):
        self.min_edge = min_edge
        self.min_confidence = min_confidence
        self.min_bucket_samples = min_bucket_samples
        self.bucket_size = bucket_size
        
        # Calibration tables: {series: {price_bucket: CalibrationBucket}}
        self._calibration: dict[str, dict[float, CalibrationBucket]] = {}
        
        # Aggregate calibration (all series combined)
        self._global_calibration: dict[float, CalibrationBucket] = {}
        
        # Track maker order fill rates
        self._fill_stats = {"placed": 0, "filled": 0, "expired": 0}
    
    def build_calibration_from_db(
        self,
        db_path: str | Path | None = None,
        series: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Build calibration tables from historical data.
        
        Uses the TRAINING set (first 80%) to build calibration tables,
        preserving the holdout (last 20%) for validation.
        """
        from app.frankenstein.historical import HistoricalHarvester
        
        conn = HistoricalHarvester.get_db(db_path)
        
        try:
            # Get all settled markets with candles
            query = """
                SELECT m.ticker, m.result, m.series_ticker
                FROM markets m
                JOIN candles c ON c.market_ticker = m.ticker
                WHERE m.result IS NOT NULL
                GROUP BY m.ticker
                HAVING COUNT(*) >= 8
                ORDER BY m.close_time ASC
            """
            markets = conn.execute(query).fetchall()
            
            # Use first 80% for calibration
            n_train = int(len(markets) * 0.80)
            train_markets = markets[:n_train]
            
            log.info("building_calibration", 
                     total_markets=len(markets),
                     train_markets=n_train)
            
            # Clear existing calibration
            self._calibration.clear()
            self._global_calibration.clear()
            
            for mkt in train_markets:
                ticker, result, series_t = mkt[0], mkt[1], mkt[2]
                
                candles = conn.execute(
                    "SELECT * FROM candles WHERE market_ticker=? ORDER BY end_period_ts",
                    (ticker,)
                ).fetchall()
                candles = [dict(c) for c in candles]
                
                if len(candles) < 8:
                    continue
                
                n = len(candles)
                
                # Sample multiple time points per market
                for time_frac in [0.30, 0.50, 0.70]:
                    idx = int(n * time_frac)
                    if idx < 2 or idx >= n:
                        continue
                    
                    c = candles[idx]
                    bid = float(c.get("bid_close") or 0)
                    ask = float(c.get("ask_close") or 0)
                    if bid > 1.5:
                        bid /= 100.0
                    if ask > 1.5:
                        ask /= 100.0
                    if bid <= 0 or ask <= 0:
                        continue
                    
                    mid = (bid + ask) / 2.0
                    bucket = self._to_bucket(mid)
                    
                    # Update series-specific calibration
                    if series_t not in self._calibration:
                        self._calibration[series_t] = {}
                    if bucket not in self._calibration[series_t]:
                        self._calibration[series_t][bucket] = CalibrationBucket(price=bucket)
                    self._calibration[series_t][bucket].total += 1
                    if result == "yes":
                        self._calibration[series_t][bucket].yes_wins += 1
                    
                    # Update global calibration
                    if bucket not in self._global_calibration:
                        self._global_calibration[bucket] = CalibrationBucket(price=bucket)
                    self._global_calibration[bucket].total += 1
                    if result == "yes":
                        self._global_calibration[bucket].yes_wins += 1
        
        finally:
            conn.close()
        
        # Save calibration
        self._save_calibration()
        
        # Return summary
        summary = {
            "series_count": len(self._calibration),
            "global_buckets": len(self._global_calibration),
            "mispricings": [],
        }
        
        for bucket_price in sorted(self._global_calibration.keys()):
            b = self._global_calibration[bucket_price]
            if b.total >= self.min_bucket_samples:
                summary["mispricings"].append({
                    "price": bucket_price,
                    "win_rate": round(b.win_rate, 4),
                    "cal_error": round(b.calibration_error, 4),
                    "samples": b.total,
                    "confidence": round(b.confidence, 3),
                })
        
        log.info("calibration_built", **{
            k: v for k, v in summary.items() if k != "mispricings"
        })
        
        return summary
    
    def evaluate_market(
        self,
        ticker: str,
        midpoint: float,
        bid: float,
        ask: float,
        time_fraction: float,
        series: str = "",
    ) -> MispricingSignal | None:
        """
        Evaluate whether a market has a tradeable mispricing.
        
        Args:
            ticker: Market ticker.
            midpoint: Current midpoint price (0-1).
            bid: Current best bid (0-1).
            ask: Current best ask (0-1).
            time_fraction: How far through market life (0=start, 1=end).
            series: Series ticker for series-specific calibration.
        
        Returns:
            MispricingSignal if tradeable, None otherwise.
        """
        if midpoint <= 0.05 or midpoint >= 0.95:
            return None  # too extreme, liquidity risk
        
        bucket = self._to_bucket(midpoint)
        
        # Get calibration data (prefer series-specific, fall back to global)
        cal = None
        if series and series in self._calibration:
            cal = self._calibration[series].get(bucket)
        if cal is None or cal.total < self.min_bucket_samples:
            cal = self._global_calibration.get(bucket)
        
        if cal is None or cal.total < self.min_bucket_samples:
            return None  # not enough data
        
        cal_error = cal.calibration_error
        confidence = cal.confidence
        
        if confidence < self.min_confidence:
            return None
        
        # Determine trade direction and edge
        if cal_error > self.min_edge:
            # YES is underpriced → buy YES
            side = "yes"
            limit_price_cents = int(bid * 100)  # maker: buy at bid
            expected_wr = cal.win_rate
            # Breakeven at 0 fee: entry_price / 100 (for YES)
            breakeven_wr = bid  # at maker rate (0 fee), breakeven = entry price
            edge = expected_wr - breakeven_wr
            
        elif cal_error < -self.min_edge:
            # YES is overpriced → buy NO (NO is underpriced)
            side = "no"
            limit_price_cents = int((1.0 - ask) * 100)  # NO price at ask
            expected_wr = 1.0 - cal.win_rate  # P(NO wins)
            breakeven_wr = (1.0 - ask)  # NO entry cost
            edge = expected_wr - breakeven_wr
            
        else:
            return None  # edge too small
        
        if edge < self.min_edge or limit_price_cents <= 0:
            return None
        
        return MispricingSignal(
            ticker=ticker,
            side=side,
            market_price=midpoint,
            limit_price_cents=limit_price_cents,
            expected_win_rate=expected_wr,
            breakeven_win_rate=breakeven_wr,
            edge=edge,
            confidence=confidence,
            time_fraction=time_fraction,
            entry_price_bucket=bucket,
        )
    
    def _to_bucket(self, price: float) -> float:
        """Convert a price to its calibration bucket."""
        return round(price / self.bucket_size) * self.bucket_size
    
    def _save_calibration(self) -> None:
        """Persist calibration tables to disk."""
        CALIBRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "global": {
                str(k): {"price": v.price, "yes_wins": v.yes_wins, "total": v.total}
                for k, v in self._global_calibration.items()
            },
            "series": {
                s: {
                    str(k): {"price": v.price, "yes_wins": v.yes_wins, "total": v.total}
                    for k, v in buckets.items()
                }
                for s, buckets in self._calibration.items()
            },
        }
        
        with open(str(CALIBRATION_PATH), "w") as f:
            json.dump(data, f, indent=2)
        
        log.info("calibration_saved", path=str(CALIBRATION_PATH))
    
    def load_calibration(self) -> bool:
        """Load calibration tables from disk."""
        if not CALIBRATION_PATH.exists():
            return False
        
        try:
            with open(str(CALIBRATION_PATH)) as f:
                data = json.load(f)
            
            self._global_calibration.clear()
            for k, v in data.get("global", {}).items():
                bucket = CalibrationBucket(
                    price=v["price"],
                    yes_wins=v["yes_wins"],
                    total=v["total"],
                )
                self._global_calibration[float(k)] = bucket
            
            self._calibration.clear()
            for series, buckets in data.get("series", {}).items():
                self._calibration[series] = {}
                for k, v in buckets.items():
                    bucket = CalibrationBucket(
                        price=v["price"],
                        yes_wins=v["yes_wins"],
                        total=v["total"],
                    )
                    self._calibration[series][float(k)] = bucket
            
            log.info("calibration_loaded",
                     global_buckets=len(self._global_calibration),
                     series=list(self._calibration.keys()))
            return True
        
        except Exception as e:
            log.error("calibration_load_failed", error=str(e))
            return False
    
    @property
    def is_ready(self) -> bool:
        """Whether calibration data is loaded."""
        return len(self._global_calibration) > 0
    
    def get_mispricing_table(self) -> list[dict]:
        """Return human-readable mispricing table."""
        rows = []
        for bucket_price in sorted(self._global_calibration.keys()):
            b = self._global_calibration[bucket_price]
            if b.total < 20:
                continue
            rows.append({
                "price": bucket_price,
                "win_rate": round(b.win_rate, 4),
                "calibration_error": round(b.calibration_error, 4),
                "samples": b.total,
                "confidence": round(b.confidence, 3),
                "tradeable": abs(b.calibration_error) >= self.min_edge and b.confidence >= self.min_confidence,
            })
        return rows


def run_maker_backtest(
    db_path: str | Path | None = None,
    series: list[str] | None = None,
    min_edge: float = 0.03,
    min_confidence: float = 0.2,
    fill_rate: float = 0.60,
    max_contracts: int = 1,
) -> dict[str, Any]:
    """
    Backtest the maker-order mispricing strategy.
    
    Uses first 80% of data to build calibration table,
    then simulates trading on the last 20% holdout.
    
    Args:
        fill_rate: Assumed fill rate for maker orders (0-1).
                   Real fill rates vary; 60% is conservative for
                   liquid crypto markets.
    """
    from app.frankenstein.historical import HistoricalHarvester
    
    strategy = MakerEdgeStrategy(
        min_edge=min_edge,
        min_confidence=min_confidence,
    )
    
    # Build calibration from training data
    cal_summary = strategy.build_calibration_from_db(db_path=db_path, series=series)
    
    # Get holdout markets
    conn = HistoricalHarvester.get_db(db_path)
    
    try:
        all_markets = conn.execute("""
            SELECT m.ticker, m.result, m.series_ticker
            FROM markets m
            JOIN candles c ON c.market_ticker = m.ticker
            WHERE m.result IS NOT NULL
            GROUP BY m.ticker
            HAVING COUNT(*) >= 8
            ORDER BY m.close_time ASC
        """).fetchall()
        
        n_train = int(len(all_markets) * 0.80)
        holdout = all_markets[n_train:]
        
        log.info("maker_backtest_start",
                 holdout_markets=len(holdout),
                 min_edge=min_edge,
                 fill_rate=fill_rate)
        
        trades = []
        skipped_no_fill = 0
        
        import random
        random.seed(42)  # reproducible fill simulation
        
        for mkt in holdout:
            ticker, result, series_t = mkt[0], mkt[1], mkt[2]
            
            candles = conn.execute(
                "SELECT * FROM candles WHERE market_ticker=? ORDER BY end_period_ts",
                (ticker,)
            ).fetchall()
            candles = [dict(c) for c in candles]
            n = len(candles)
            if n < 8:
                continue
            
            # Evaluate at multiple time points
            for time_frac in [0.30, 0.50, 0.70]:
                idx = int(n * time_frac)
                if idx < 2 or idx >= n:
                    continue
                
                c = candles[idx]
                bid = float(c.get("bid_close") or 0)
                ask = float(c.get("ask_close") or 0)
                if bid > 1.5:
                    bid /= 100.0
                if ask > 1.5:
                    ask /= 100.0
                if bid <= 0 or ask <= 0:
                    continue
                mid = (bid + ask) / 2.0
                
                signal = strategy.evaluate_market(
                    ticker=ticker,
                    midpoint=mid,
                    bid=bid,
                    ask=ask,
                    time_fraction=time_frac,
                    series=series_t,
                )
                
                if signal is None:
                    continue
                
                # Simulate fill rate
                if random.random() > fill_rate:
                    skipped_no_fill += 1
                    continue
                
                # Simulate trade
                entry_cents = signal.limit_price_cents
                correct = signal.side == result
                
                if correct:
                    pnl_cents = (100 - entry_cents) * max_contracts  # 0 fee (maker)
                else:
                    pnl_cents = -entry_cents * max_contracts  # 0 fee
                
                trades.append({
                    "ticker": ticker,
                    "side": signal.side,
                    "entry_cents": entry_cents,
                    "edge": signal.edge,
                    "confidence": signal.confidence,
                    "time_frac": time_frac,
                    "correct": correct,
                    "pnl_cents": pnl_cents,
                    "bucket": signal.entry_price_bucket,
                })
    
    finally:
        conn.close()
    
    # Compute results
    if not trades:
        return {
            "success": False,
            "error": "No trades generated",
            "calibration": cal_summary,
        }
    
    total_trades = len(trades)
    wins = sum(1 for t in trades if t["correct"])
    total_pnl = sum(t["pnl_cents"] for t in trades)
    
    # Drawdown
    balance = 0
    peak = 0
    max_dd = 0
    for t in trades:
        balance += t["pnl_cents"]
        peak = max(peak, balance)
        dd = peak - balance
        max_dd = max(max_dd, dd)
    
    # Sharpe (annualized from per-trade)
    pnls = [t["pnl_cents"] for t in trades]
    pnl_mean = np.mean(pnls)
    pnl_std = np.std(pnls)
    sharpe = (pnl_mean / pnl_std * math.sqrt(252)) if pnl_std > 0 else 0
    
    # Profit factor
    gross_wins = sum(t["pnl_cents"] for t in trades if t["pnl_cents"] > 0)
    gross_losses = abs(sum(t["pnl_cents"] for t in trades if t["pnl_cents"] < 0))
    profit_factor = gross_wins / max(gross_losses, 1)
    
    # By-side breakdown
    yes_trades = [t for t in trades if t["side"] == "yes"]
    no_trades = [t for t in trades if t["side"] == "no"]
    
    # By-time breakdown
    time_breakdown = {}
    for tf in [0.30, 0.50, 0.70]:
        tf_trades = [t for t in trades if t["time_frac"] == tf]
        if tf_trades:
            tf_wins = sum(1 for t in tf_trades if t["correct"])
            tf_pnl = sum(t["pnl_cents"] for t in tf_trades)
            time_breakdown[str(tf)] = {
                "trades": len(tf_trades),
                "win_rate": round(tf_wins / len(tf_trades), 4),
                "pnl": f"${tf_pnl / 100:.2f}",
            }
    
    results = {
        "success": True,
        "total_trades": total_trades,
        "signals_generated": total_trades + skipped_no_fill,
        "skipped_no_fill": skipped_no_fill,
        "fill_rate_assumed": fill_rate,
        "wins": wins,
        "losses": total_trades - wins,
        "win_rate": round(wins / total_trades, 4),
        "total_pnl": f"${total_pnl / 100:.2f}",
        "total_pnl_cents": total_pnl,
        "avg_pnl_per_trade": f"${total_pnl / total_trades / 100:.3f}",
        "max_drawdown": f"${max_dd / 100:.2f}",
        "sharpe_ratio": round(sharpe, 2),
        "profit_factor": round(profit_factor, 3),
        "fee_structure": "maker (0¢ per side)",
        "yes_trades": len(yes_trades),
        "yes_wr": round(sum(1 for t in yes_trades if t["correct"]) / max(len(yes_trades), 1), 4),
        "yes_pnl": f"${sum(t['pnl_cents'] for t in yes_trades) / 100:.2f}",
        "no_trades": len(no_trades),
        "no_wr": round(sum(1 for t in no_trades if t["correct"]) / max(len(no_trades), 1), 4),
        "no_pnl": f"${sum(t['pnl_cents'] for t in no_trades) / 100:.2f}",
        "time_breakdown": time_breakdown,
        "calibration_summary": cal_summary.get("mispricings", []),
    }
    
    log.info("maker_backtest_complete", **{
        k: v for k, v in results.items()
        if k not in ("calibration_summary", "time_breakdown")
    })
    
    return results


# ── Standalone ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Maker-Order Mispricing Strategy")
    parser.add_argument("--min-edge", type=float, default=0.03)
    parser.add_argument("--fill-rate", type=float, default=0.60)
    parser.add_argument("--series", nargs="+", default=None)
    parser.add_argument("--build-calibration", action="store_true")
    parser.add_argument("--show-table", action="store_true")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    
    strategy = MakerEdgeStrategy(min_edge=args.min_edge)
    
    if args.build_calibration or args.backtest:
        if args.backtest:
            results = run_maker_backtest(
                series=args.series,
                min_edge=args.min_edge,
                fill_rate=args.fill_rate,
            )
            if args.json:
                print(json.dumps(results, indent=2))
            else:
                print(f"\n📊 Maker-Order Backtest Results:")
                print(f"{'='*50}")
                for k, v in results.items():
                    if k in ("calibration_summary",):
                        continue
                    if k == "time_breakdown":
                        print(f"\n  Time Breakdown:")
                        for tf, data in v.items():
                            print(f"    @{tf}: {data}")
                    else:
                        print(f"  {k}: {v}")
        else:
            summary = strategy.build_calibration_from_db(series=args.series)
            if args.json:
                print(json.dumps(summary, indent=2))
            else:
                print(f"\n📊 Calibration Table:")
                for mp in summary.get("mispricings", []):
                    marker = " ✅ TRADEABLE" if abs(mp["cal_error"]) >= args.min_edge else ""
                    print(f"  {mp['price']:.2f}: WR={mp['win_rate']:.1%} "
                          f"err={mp['cal_error']:+.3f} "
                          f"n={mp['samples']} conf={mp['confidence']:.2f}{marker}")
    
    if args.show_table:
        if not strategy.is_ready:
            strategy.load_calibration()
        if strategy.is_ready:
            table = strategy.get_mispricing_table()
            print(f"\n📊 Mispricing Table:")
            for row in table:
                marker = " ✅" if row["tradeable"] else ""
                print(f"  {row['price']:.2f}: WR={row['win_rate']:.1%} "
                      f"err={row['calibration_error']:+.3f} "
                      f"n={row['samples']} conf={row['confidence']:.2f}{marker}")
        else:
            print("No calibration data. Run --build-calibration first.")
