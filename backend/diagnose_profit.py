#!/usr/bin/env python3
"""
Diagnose exactly why the backtest can't capture profit despite model having signal.

Checks:
  1. How much of the model's AUC comes from implied_prob (leakage test)
  2. Whether calibration compresses predictions too much
  3. What the actual edge/EV distribution looks like on holdout
  4. How many trades survive each backtest filter
"""
import sys, json
import numpy as np
import xgboost as xgb

sys.path.insert(0, ".")

from app.frankenstein.pretrained import load_pretrained_model
from app.frankenstein.historical import HistoricalHarvester
from app.frankenstein.historical_features import (
    build_training_dataset, compute_features_from_candles
)
from app.ai.features import MarketFeatures

TAKER_FEE = 0.07  # 7c per side


def main():
    # ── 1. Load current model ──
    loaded = load_pretrained_model()
    if not loaded:
        print("NO MODEL"); return
    model, calibration, meta = loaded
    feature_names = MarketFeatures.feature_names()
    print(f"Model: {meta.get('holdout_auc'):.4f} AUC, "
          f"{meta.get('holdout_accuracy'):.3f} acc, "
          f"{meta.get('train_samples')} train samples")

    # ── 2. Get holdout markets ──
    markets = HistoricalHarvester.get_markets_with_candles(
        series=["KXBTC15M", "KXETH15M"], min_candles=10,
    )
    n_skip = int(len(markets) * 0.80)
    holdout = markets[n_skip:]
    print(f"\nHoldout markets: {len(holdout)}")

    conn = HistoricalHarvester.get_db()

    # ── 3. Feature leakage analysis ──
    # Find which features are derived from implied_prob (current price)
    price_derived_features = {
        "implied_prob", "prob_distance_from_50", "extreme_prob",
        "log_odds", "price_bin", "kelly_edge", "settlement_confidence",
        "price_time_signal", "convergence_rate",
    }
    price_derived_indices = [
        i for i, name in enumerate(feature_names)
        if name in price_derived_features
    ]
    print(f"\nPrice-derived features ({len(price_derived_indices)}): "
          f"{[feature_names[i] for i in price_derived_indices]}")

    # ── 4. Collect holdout predictions with diagnostics ──
    rows = []
    try:
        for m in holdout:
            ticker = m["ticker"]
            result = m["result"]
            candle_rows = conn.execute(
                "SELECT * FROM candles WHERE market_ticker = ? ORDER BY end_period_ts ASC",
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

            X = np.nan_to_num(feat.to_array().reshape(1, -1), nan=0.0)

            # Raw prediction
            p_raw = float(model.predict(xgb.DMatrix(X, feature_names=feature_names))[0])
            # Calibrated
            p_cal = calibration.calibrate(p_raw) if calibration.is_ready else p_raw

            # Prediction WITHOUT price-derived features (zero them out)
            X_clean = X.copy()
            for idx_f in price_derived_indices:
                X_clean[0, idx_f] = 0.0
            p_noprice = float(model.predict(xgb.DMatrix(X_clean, feature_names=feature_names))[0])

            rows.append({
                "ticker": ticker,
                "result": result,
                "mid": mid,
                "spread": spread,
                "p_raw": p_raw,
                "p_cal": p_cal,
                "p_noprice": p_noprice,
            })
    finally:
        conn.close()

    print(f"Holdout samples: {len(rows)}")

    # ── 5. Analyze predictions ──
    mids = np.array([r["mid"] for r in rows])
    p_raws = np.array([r["p_raw"] for r in rows])
    p_cals = np.array([r["p_cal"] for r in rows])
    p_noprices = np.array([r["p_noprice"] for r in rows])
    labels = np.array([1.0 if r["result"] == "yes" else 0.0 for r in rows])
    spreads = np.array([r["spread"] for r in rows])

    from sklearn.metrics import roc_auc_score, brier_score_loss

    print(f"\n{'='*60}")
    print("PREDICTION DISTRIBUTION ANALYSIS")
    print(f"{'='*60}")
    print(f"  Market midpoints:     mean={mids.mean():.3f}  std={mids.std():.3f}")
    print(f"  Raw predictions:      mean={p_raws.mean():.3f}  std={p_raws.std():.3f}")
    print(f"  Calibrated preds:     mean={p_cals.mean():.3f}  std={p_cals.std():.3f}")
    print(f"  No-price preds:       mean={p_noprices.mean():.3f}  std={p_noprices.std():.3f}")

    print(f"\n  Raw AUC:       {roc_auc_score(labels, p_raws):.4f}")
    print(f"  Calibrated AUC:{roc_auc_score(labels, p_cals):.4f}")
    print(f"  No-price AUC:  {roc_auc_score(labels, p_noprices):.4f}")
    print(f"  Market-only AUC:{roc_auc_score(labels, mids):.4f}")

    print(f"\n  Raw Brier:      {brier_score_loss(labels, p_raws):.4f}")
    print(f"  Calibrated Brier:{brier_score_loss(labels, p_cals):.4f}")
    print(f"  No-price Brier:  {brier_score_loss(labels, p_noprices):.4f}")
    print(f"  Market Brier:    {brier_score_loss(labels, mids):.4f}")

    # ── 6. Edge distribution ──
    print(f"\n{'='*60}")
    print("EDGE DISTRIBUTION (raw model vs market)")
    print(f"{'='*60}")
    edges_raw = p_raws - mids
    edges_cal = p_cals - mids
    edges_noprice = p_noprices - mids

    for name, edges in [("Raw", edges_raw), ("Calibrated", edges_cal), ("No-price", edges_noprice)]:
        abs_e = np.abs(edges)
        print(f"\n  {name} edges:")
        print(f"    mean={edges.mean():.4f}  std={edges.std():.4f}")
        print(f"    |edge| percentiles: 25%={np.percentile(abs_e,25):.4f}  "
              f"50%={np.percentile(abs_e,50):.4f}  "
              f"75%={np.percentile(abs_e,75):.4f}  "
              f"95%={np.percentile(abs_e,95):.4f}")

    # ── 7. How many trades survive each filter ──
    print(f"\n{'='*60}")
    print("FILTER FUNNEL (simulating backtest filters)")
    print(f"{'='*60}")

    # Use calibrated predictions as the backtest does
    n_total = len(rows)
    surviving = list(range(n_total))

    # Price filter: 0.10 to 0.90
    surviving = [i for i in surviving if 0.10 <= mids[i] <= 0.90]
    print(f"  After price filter (0.10-0.90):     {len(surviving)}")

    # Spread filter: < 0.10
    surviving = [i for i in surviving if spreads[i] <= 0.10]
    print(f"  After spread filter (<0.10):         {len(surviving)}")

    # Edge filter: |edge| >= 0.03
    surviving_03 = [i for i in surviving if abs(edges_cal[i]) >= 0.03]
    print(f"  After edge filter (>=0.03):          {len(surviving_03)}")

    surviving_05 = [i for i in surviving if abs(edges_cal[i]) >= 0.05]
    print(f"  After edge filter (>=0.05):          {len(surviving_05)}")

    # EV filter (positive expected value after fees)
    def ev_positive(i):
        edge = edges_cal[i]
        mid = mids[i]
        spr = spreads[i]
        side = "yes" if edge > 0 else "no"
        p_win = p_cals[i] if side == "yes" else 1.0 - p_cals[i]
        if side == "yes":
            entry = min(0.99, max(0.01, mid + spr/2))
        else:
            entry = min(0.99, max(0.01, (1.0-mid) + spr/2))
        ev = p_win * (1.0 - entry - 2*TAKER_FEE) + (1-p_win)*(-entry - TAKER_FEE)
        return ev > 0, ev

    surviving_ev = []
    for i in surviving_03:
        ok, ev = ev_positive(i)
        if ok:
            surviving_ev.append((i, ev))
    print(f"  After EV>0 filter:                   {len(surviving_ev)}")

    # Kelly filter (p > real_cost)
    surviving_kelly = []
    for i, ev in surviving_ev:
        edge = edges_cal[i]
        mid = mids[i]
        spr = spreads[i]
        side = "yes" if edge > 0 else "no"
        p_win = p_cals[i] if side == "yes" else 1.0 - p_cals[i]
        if side == "yes":
            entry = min(0.99, max(0.01, mid + spr/2))
        else:
            entry = min(0.99, max(0.01, (1.0-mid) + spr/2))
        real_cost = entry + TAKER_FEE
        net_win = (1.0 - TAKER_FEE) - entry
        if p_win > real_cost and net_win > 0:
            surviving_kelly.append(i)
    print(f"  After Kelly filter (p>cost):         {len(surviving_kelly)}")

    # ── 8. Profit simulation at different thresholds ──
    print(f"\n{'='*60}")
    print("PROFIT SIMULATION (1-contract fixed, with fees)")
    print(f"{'='*60}")

    for min_e in [0.02, 0.03, 0.04, 0.05]:
        for use_cal in [False, True]:
            pred_name = "calibrated" if use_cal else "raw"
            preds = p_cals if use_cal else p_raws
            edges = preds - mids

            trades = []
            for i in range(n_total):
                if mids[i] < 0.10 or mids[i] > 0.90:
                    continue
                if spreads[i] > 0.12:
                    continue

                edge = edges[i]
                if abs(edge) < min_e:
                    continue

                side = "yes" if edge > 0 else "no"
                correct = side == rows[i]["result"]

                # Simple fixed-size P&L (like evaluate_potential)
                price_c = int(mids[i] * 100)
                if correct:
                    gross = 100 - price_c
                    net = gross - 14  # buy + sell fee
                else:
                    gross = -price_c
                    net = gross - 7  # only buy fee on loss

                trades.append({"correct": correct, "net": net, "edge": abs(edge)})

            if not trades:
                continue
            n = len(trades)
            wins = sum(1 for t in trades if t["correct"])
            pnl = sum(t["net"] for t in trades)
            print(f"  edge>={min_e:.2f} ({pred_name:>10}): {n:>5} trades, "
                  f"{wins/n:.1%} WR, ${pnl/100:>+8.2f} "
                  f"(avg ${pnl/n/100:>+.3f}/trade)")

    # ── 9. The key question: can we beat the market WITHOUT implied_prob? ──
    print(f"\n{'='*60}")
    print("CAN WE BEAT THE MARKET WITHOUT PRICE FEATURES?")
    print(f"{'='*60}")
    # Simulate with p_noprice predictions
    edges_np = p_noprices - mids
    for min_e in [0.02, 0.03, 0.05, 0.10]:
        trades = []
        for i in range(n_total):
            if mids[i] < 0.10 or mids[i] > 0.90:
                continue
            if spreads[i] > 0.12:
                continue
            if abs(edges_np[i]) < min_e:
                continue

            side = "yes" if edges_np[i] > 0 else "no"
            correct = side == rows[i]["result"]
            price_c = int(mids[i] * 100)
            if correct:
                net = (100 - price_c) - 14
            else:
                net = -price_c - 7
            trades.append({"correct": correct, "net": net})

        if not trades:
            print(f"  edge>={min_e:.2f}: 0 trades")
            continue
        n = len(trades)
        wins = sum(1 for t in trades if t["correct"])
        pnl = sum(t["net"] for t in trades)
        print(f"  edge>={min_e:.2f}: {n:>5} trades, "
              f"{wins/n:.1%} WR, ${pnl/100:>+8.2f}")


if __name__ == "__main__":
    main()
