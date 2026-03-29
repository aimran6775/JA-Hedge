#!/usr/bin/env python3
"""
The REAL profit path: XGBoost model predictions + maker orders.

From our diagnosis:
  - XGBoost model at edge>=0.03 gives 67.5% WR on 1,180 trades (taker: +$68)
  - BUT the 14¢ taker fee eats most of the profit (avg $0.058/trade)
  - With MAKER orders (0¢ fee), the same model predictions would net
    MUCH more per trade because we're not losing 7-14¢ to fees

This script tests: model-based predictions + maker (bid) order prices.
"""
import sys, random
import numpy as np
import xgboost as xgb

sys.path.insert(0, ".")

from app.frankenstein.pretrained import load_pretrained_model
from app.frankenstein.historical import HistoricalHarvester
from app.frankenstein.historical_features import compute_features_from_candles
from app.ai.features import MarketFeatures

random.seed(42)

def main():
    loaded = load_pretrained_model()
    if not loaded:
        print("NO MODEL"); return
    model, calibration, meta = loaded
    feature_names = MarketFeatures.feature_names()

    markets = HistoricalHarvester.get_markets_with_candles(
        series=["KXBTC15M", "KXETH15M"], min_candles=10,
    )
    n_skip = int(len(markets) * 0.80)
    holdout = markets[n_skip:]
    print(f"Holdout markets: {len(holdout)}")

    conn = HistoricalHarvester.get_db()

    rows = []
    try:
        for m in holdout:
            ticker = m["ticker"]
            result = m["result"]
            candle_rows = conn.execute(
                "SELECT * FROM candles WHERE market_ticker=? ORDER BY end_period_ts ASC",
                (ticker,)
            ).fetchall()
            candles = [dict(r) for r in candle_rows]
            if len(candles) < 10:
                continue

            total = len(candles)
            first_ts = candles[0]["end_period_ts"]
            last_ts = candles[-1]["end_period_ts"]
            duration_h = max((last_ts - first_ts) / 3600.0, 0.05)

            frac = 0.30
            idx = int(total * (1.0 - frac))
            if idx < 5:
                continue

            feat = compute_features_from_candles(
                candles[:idx], idx, total, frac * duration_h, duration_h, result,
            )
            if feat is None:
                continue

            mid = float(feat.midpoint)
            spread = float(feat.spread)
            if mid < 0.10 or mid > 0.90:
                continue
            if spread > 0.12:
                continue

            # Get bid/ask from the candle
            c = candles[idx - 1]
            bid = float(c.get("bid_close") or 0)
            ask = float(c.get("ask_close") or 0)
            if bid > 1.5: bid /= 100
            if ask > 1.5: ask /= 100
            if bid <= 0 or ask <= 0:
                bid = mid - spread/2
                ask = mid + spread/2

            X = np.nan_to_num(feat.to_array().reshape(1, -1), nan=0.0)
            p_yes = float(model.predict(xgb.DMatrix(X, feature_names=feature_names))[0])
            if calibration.is_ready:
                p_yes = calibration.calibrate(p_yes)

            edge = p_yes - mid
            side = "yes" if edge > 0 else "no"
            abs_edge = abs(edge)

            rows.append({
                "ticker": ticker,
                "result": result,
                "mid": mid,
                "bid": bid,
                "ask": ask,
                "spread": spread,
                "p_yes": p_yes,
                "edge": edge,
                "abs_edge": abs_edge,
                "side": side,
            })
    finally:
        conn.close()

    print(f"Eligible markets: {len(rows)}")

    # Test different scenarios
    for fill_rate in [1.0, 0.70, 0.50]:
        print(f"\n{'='*70}")
        print(f"FILL RATE = {fill_rate:.0%}")
        print(f"{'='*70}")

        for min_edge in [0.02, 0.03, 0.05, 0.08]:
            for fee_scenario in ["taker_14c", "hybrid_7c", "maker_0c"]:
                signals = [r for r in rows if r["abs_edge"] >= min_edge]
                if not signals:
                    continue

                # Simulate fills
                trades = []
                for r in signals:
                    if fill_rate < 1.0 and random.random() > fill_rate:
                        continue

                    correct = r["side"] == r["result"]

                    if fee_scenario == "taker_14c":
                        # Taker: buy at ask, pay 7¢ both sides
                        if r["side"] == "yes":
                            entry_c = int(min(r["ask"], 0.99) * 100)
                        else:
                            entry_c = int(min(1.0 - r["bid"], 0.99) * 100)
                        buy_fee = 7
                        sell_fee = 7 if correct else 0  # only pay sell fee if we sell
                        if correct:
                            pnl = (100 - entry_c) - buy_fee - sell_fee
                        else:
                            pnl = -entry_c - buy_fee

                    elif fee_scenario == "hybrid_7c":
                        # Maker buy (0¢), taker sell (7¢) or settlement (0¢)
                        if r["side"] == "yes":
                            entry_c = int(r["bid"] * 100)  # buy at bid (maker)
                        else:
                            entry_c = int((1.0 - r["ask"]) * 100)  # buy NO at maker
                        if correct:
                            pnl = 100 - entry_c  # settlement payout, no fees
                        else:
                            pnl = -entry_c  # lose entry, no fees

                    elif fee_scenario == "maker_0c":
                        # Pure maker: 0¢ both sides, buy at bid
                        if r["side"] == "yes":
                            entry_c = int(r["bid"] * 100)
                        else:
                            entry_c = int((1.0 - r["ask"]) * 100)
                        if correct:
                            pnl = 100 - entry_c
                        else:
                            pnl = -entry_c

                    if entry_c <= 0 or entry_c >= 100:
                        continue
                    trades.append({"pnl": pnl, "correct": correct, "entry": entry_c})

                if not trades:
                    continue
                n = len(trades)
                wins = sum(1 for t in trades if t["correct"])
                total_pnl = sum(t["pnl"] for t in trades)
                avg_entry = sum(t["entry"] for t in trades) / n
                print(f"  edge>={min_edge:.2f} {fee_scenario:>12}: "
                      f"{n:>5} trades, {wins/n:.1%} WR, "
                      f"${total_pnl/100:>+8.2f} "
                      f"(avg ${total_pnl/n/100:>+.3f}/trade, entry={avg_entry:.0f}¢)")


if __name__ == "__main__":
    main()
