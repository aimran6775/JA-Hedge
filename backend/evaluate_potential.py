#!/usr/bin/env python3
import sys
import numpy as np
import xgboost as xgb

sys.path.insert(0, ".")

from app.frankenstein.pretrained import load_pretrained_model
from app.frankenstein.historical import HistoricalHarvester
from app.frankenstein.historical_features import compute_features_from_candles
from app.ai.features import MarketFeatures


def main() -> None:
    loaded = load_pretrained_model()
    if not loaded:
        print("NO_MODEL")
        return

    model, calibration, _ = loaded
    feature_names = MarketFeatures.feature_names()

    markets = HistoricalHarvester.get_markets_with_candles(
        series=["KXBTC15M", "KXETH15M"],
        min_candles=10,
    )
    n_skip = int(len(markets) * 0.80)
    markets = markets[n_skip:]
    print(f"holdout_markets={len(markets)}")

    conn = HistoricalHarvester.get_db()
    rows_eval = []

    try:
        for m in markets:
            ticker = m["ticker"]
            result = m["result"]
            candle_rows = conn.execute(
                """
                SELECT * FROM candles
                WHERE market_ticker = ?
                ORDER BY end_period_ts ASC
                """,
                (ticker,),
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

            X = np.nan_to_num(feat.to_array().reshape(1, -1), nan=0.0)
            p_yes = float(model.predict(xgb.DMatrix(X, feature_names=feature_names))[0])
            if calibration.is_ready:
                p_yes = calibration.calibrate(p_yes)

            edge = p_yes - mid
            side = "yes" if edge > 0 else "no"
            abs_edge = abs(edge)

            correct = side == result
            price_cents = int(mid * 100)
            buy_fee = 7
            sell_fee = 7
            buy_cost = price_cents

            if correct:
                gross = 100 - buy_cost
                net = gross - (buy_fee + sell_fee)
            else:
                gross = -buy_cost
                net = gross - buy_fee

            rows_eval.append((abs_edge, correct, net))
    finally:
        conn.close()

    print(f"eligible_markets={len(rows_eval)}")

    for th in [0.02, 0.03, 0.05, 0.08, 0.10, 0.15]:
        sel = [r for r in rows_eval if r[0] >= th]
        if not sel:
            print(f"th={th:.2f} trades=0")
            continue
        n = len(sel)
        wins = sum(1 for r in sel if r[1])
        wr = wins / n
        pnl = sum(r[2] for r in sel)
        avg = pnl / n
        print(
            f"th={th:.2f} trades={n} win_rate={wr:.3f} pnl=${pnl/100:.2f} avg=${avg/100:.3f}"
        )

    rows_eval.sort(key=lambda x: x[0], reverse=True)
    for n in [100, 250, 500, 1000]:
        sel = rows_eval[: min(n, len(rows_eval))]
        if not sel:
            continue
        wins = sum(1 for r in sel if r[1])
        wr = wins / len(sel)
        pnl = sum(r[2] for r in sel)
        print(f"top={n} win_rate={wr:.3f} pnl=${pnl/100:.2f} avg=${(pnl/len(sel))/100:.3f}")


if __name__ == "__main__":
    main()
