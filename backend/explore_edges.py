#!/usr/bin/env python3
"""
Explore REAL tradeable edges in 15-minute crypto prediction markets.

Instead of predicting outcomes (which the market already does at 95% AUC),
look for short-term PRICE MOVEMENT patterns that let us buy low / sell high
BEFORE settlement.

Edges to test:
  1. Mean-reversion: extreme moves tend to snap back
  2. Momentum: strong trends in last 3 candles continue
  3. Volume-spike: high volume = information arrival = directional move
  4. Time-of-day: are there patterns in when prices move?
  5. Settlement drift: do prices drift predictably toward 0 or 1 in final candles?
  6. Spread compression: narrow spreads = consensus = resolution coming
"""
import sys, math
import numpy as np

sys.path.insert(0, ".")

from app.frankenstein.historical import HistoricalHarvester


def main():
    conn = HistoricalHarvester.get_db()

    # Get all markets with enough candles
    markets = conn.execute("""
        SELECT m.ticker, m.result, m.series_ticker,
               COUNT(*) as n_candles
        FROM markets m
        JOIN candles c ON c.market_ticker = m.ticker
        WHERE m.result IS NOT NULL
        GROUP BY m.ticker
        HAVING n_candles >= 10
        ORDER BY m.close_time ASC
    """).fetchall()

    print(f"Total markets with 10+ candles: {len(markets)}")

    # Use last 20% as test set
    n_test = int(len(markets) * 0.20)
    train_markets = markets[:-n_test]
    test_markets = markets[-n_test:]
    print(f"Train: {len(train_markets)}, Test: {len(test_markets)}")

    # ── Strategy 1: Settlement Drift ──
    # In the LAST few candles of a 15-min market, price should converge
    # to 0 or 1. If at 70% time through, price is >0.60, the market
    # probably resolves YES. But the question is: does BUYING at that
    # point generate profit after fees?
    print(f"\n{'='*60}")
    print("STRATEGY 1: SETTLEMENT DRIFT (buy late, sell at settlement)")
    print(f"{'='*60}")

    for entry_frac in [0.50, 0.60, 0.70, 0.80]:
        for threshold in [0.55, 0.60, 0.65]:
            trades_yes, trades_no = [], []
            for mkt in test_markets:
                ticker, result = mkt[0], mkt[1]
                candles = conn.execute(
                    "SELECT * FROM candles WHERE market_ticker = ? ORDER BY end_period_ts",
                    (ticker,)
                ).fetchall()
                candles = [dict(c) for c in candles]
                n = len(candles)
                entry_idx = int(n * entry_frac)
                if entry_idx < 3 or entry_idx >= n:
                    continue

                c = candles[entry_idx]
                bid = float(c.get("bid_close") or 0)
                ask = float(c.get("ask_close") or 0)
                if bid <= 0 or ask <= 0:
                    continue
                if bid > 1.5:
                    bid /= 100.0
                    ask /= 100.0
                mid = (bid + ask) / 2.0
                spread = ask - bid

                if mid > threshold:
                    # Buy YES
                    entry_price_c = int(min(ask, 0.99) * 100)
                    if result == "yes":
                        pnl = (100 - entry_price_c) - 14  # win: payout - cost - fees
                    else:
                        pnl = -entry_price_c - 7  # lose: cost + buy fee
                    trades_yes.append(pnl)
                elif mid < (1.0 - threshold):
                    # Buy NO
                    no_price_c = int(min((1.0 - bid), 0.99) * 100)
                    if result == "no":
                        pnl = (100 - no_price_c) - 14
                    else:
                        pnl = -no_price_c - 7
                    trades_no.append(pnl)

            all_trades = trades_yes + trades_no
            if len(all_trades) < 20:
                continue
            n_trades = len(all_trades)
            wins = sum(1 for t in all_trades if t > 0)
            total_pnl = sum(all_trades)
            print(f"  entry@{entry_frac:.0%} th={threshold:.2f}: "
                  f"{n_trades:>5} trades, {wins/n_trades:.1%} WR, "
                  f"${total_pnl/100:>+8.2f} (avg ${total_pnl/n_trades/100:>+.3f})")

    # ── Strategy 2: Mean Reversion ──
    # If price moved sharply in last 3 candles, bet on reversal
    print(f"\n{'='*60}")
    print("STRATEGY 2: MEAN REVERSION (fade sharp moves)")
    print(f"{'='*60}")

    for lookback in [3, 5]:
        for move_threshold in [0.03, 0.05, 0.08]:
            trades = []
            for mkt in test_markets:
                ticker, result = mkt[0], mkt[1]
                candles = conn.execute(
                    "SELECT * FROM candles WHERE market_ticker = ? ORDER BY end_period_ts",
                    (ticker,)
                ).fetchall()
                candles = [dict(c) for c in candles]
                n = len(candles)

                # Look at candles 60-80% through the market
                for check_pct in [0.50, 0.60, 0.70]:
                    check_idx = int(n * check_pct)
                    if check_idx < lookback + 1 or check_idx >= n - 2:
                        continue

                    prices = []
                    for i in range(check_idx - lookback, check_idx + 1):
                        c = candles[i]
                        bid = float(c.get("bid_close") or 0)
                        ask = float(c.get("ask_close") or 0)
                        if bid > 1.5: bid /= 100
                        if ask > 1.5: ask /= 100
                        if bid > 0 and ask > 0:
                            prices.append((bid + ask) / 2.0)

                    if len(prices) < lookback:
                        continue

                    move = prices[-1] - prices[0]
                    if abs(move) < move_threshold:
                        continue

                    # Fade the move: if price went UP, buy NO (expect reversion)
                    entry_c = candles[check_idx]
                    bid = float(entry_c.get("bid_close") or 0)
                    ask = float(entry_c.get("ask_close") or 0)
                    if bid > 1.5: bid /= 100
                    if ask > 1.5: ask /= 100
                    if bid <= 0 or ask <= 0:
                        continue
                    mid = (bid + ask) / 2.0

                    if move > 0:
                        # Price went up → fade → buy NO
                        side = "no"
                        entry_price_c = int(min((1.0 - bid), 0.99) * 100)
                    else:
                        # Price went down → fade → buy YES
                        side = "yes"
                        entry_price_c = int(min(ask, 0.99) * 100)

                    correct = side == result
                    if correct:
                        pnl = (100 - entry_price_c) - 14
                    else:
                        pnl = -entry_price_c - 7
                    trades.append(pnl)

            if len(trades) < 20:
                continue
            n_t = len(trades)
            wins = sum(1 for t in trades if t > 0)
            total = sum(trades)
            print(f"  lb={lookback} move>={move_threshold:.2f}: "
                  f"{n_t:>5} trades, {wins/n_t:.1%} WR, "
                  f"${total/100:>+8.2f} (avg ${total/n_t/100:>+.3f})")

    # ── Strategy 3: Momentum (follow the trend) ──
    print(f"\n{'='*60}")
    print("STRATEGY 3: MOMENTUM (follow strong trends)")
    print(f"{'='*60}")

    for lookback in [3, 5]:
        for move_threshold in [0.03, 0.05, 0.08]:
            trades = []
            for mkt in test_markets:
                ticker, result = mkt[0], mkt[1]
                candles = conn.execute(
                    "SELECT * FROM candles WHERE market_ticker = ? ORDER BY end_period_ts",
                    (ticker,)
                ).fetchall()
                candles = [dict(c) for c in candles]
                n = len(candles)

                for check_pct in [0.50, 0.60, 0.70]:
                    check_idx = int(n * check_pct)
                    if check_idx < lookback + 1 or check_idx >= n - 2:
                        continue

                    prices = []
                    for i in range(check_idx - lookback, check_idx + 1):
                        c = candles[i]
                        bid = float(c.get("bid_close") or 0)
                        ask = float(c.get("ask_close") or 0)
                        if bid > 1.5: bid /= 100
                        if ask > 1.5: ask /= 100
                        if bid > 0 and ask > 0:
                            prices.append((bid + ask) / 2.0)

                    if len(prices) < lookback:
                        continue

                    move = prices[-1] - prices[0]
                    if abs(move) < move_threshold:
                        continue

                    entry_c = candles[check_idx]
                    bid = float(entry_c.get("bid_close") or 0)
                    ask = float(entry_c.get("ask_close") or 0)
                    if bid > 1.5: bid /= 100
                    if ask > 1.5: ask /= 100
                    if bid <= 0 or ask <= 0:
                        continue

                    if move > 0:
                        # Price trending up → buy YES (momentum)
                        side = "yes"
                        entry_price_c = int(min(ask, 0.99) * 100)
                    else:
                        # Price trending down → buy NO (momentum)
                        side = "no"
                        entry_price_c = int(min((1.0 - bid), 0.99) * 100)

                    correct = side == result
                    if correct:
                        pnl = (100 - entry_price_c) - 14
                    else:
                        pnl = -entry_price_c - 7
                    trades.append(pnl)

            if len(trades) < 20:
                continue
            n_t = len(trades)
            wins = sum(1 for t in trades if t > 0)
            total = sum(trades)
            print(f"  lb={lookback} move>={move_threshold:.2f}: "
                  f"{n_t:>5} trades, {wins/n_t:.1%} WR, "
                  f"${total/100:>+8.2f} (avg ${total/n_t/100:>+.3f})")

    # ── Strategy 4: Volume Spike ──
    print(f"\n{'='*60}")
    print("STRATEGY 4: VOLUME SPIKE (trade with information arrival)")
    print(f"{'='*60}")

    for vol_mult in [2.0, 3.0, 5.0]:
        trades = []
        for mkt in test_markets:
            ticker, result = mkt[0], mkt[1]
            candles = conn.execute(
                "SELECT * FROM candles WHERE market_ticker = ? ORDER BY end_period_ts",
                (ticker,)
            ).fetchall()
            candles = [dict(c) for c in candles]
            n = len(candles)

            for check_pct in [0.40, 0.50, 0.60, 0.70]:
                check_idx = int(n * check_pct)
                if check_idx < 5 or check_idx >= n - 1:
                    continue

                # Current candle volume vs average of previous 5
                vols = [float(candles[i].get("volume") or 0) for i in range(check_idx-5, check_idx)]
                cur_vol = float(candles[check_idx].get("volume") or 0)
                avg_vol = sum(vols) / max(len(vols), 1)
                if avg_vol <= 0 or cur_vol < avg_vol * vol_mult:
                    continue

                # Volume spike detected — which direction?
                c = candles[check_idx]
                bid = float(c.get("bid_close") or 0)
                ask = float(c.get("ask_close") or 0)
                if bid > 1.5: bid /= 100
                if ask > 1.5: ask /= 100
                if bid <= 0 or ask <= 0:
                    continue
                mid = (bid + ask) / 2.0

                prev_c = candles[check_idx - 1]
                prev_bid = float(prev_c.get("bid_close") or 0)
                prev_ask = float(prev_c.get("ask_close") or 0)
                if prev_bid > 1.5: prev_bid /= 100
                if prev_ask > 1.5: prev_ask /= 100
                if prev_bid <= 0 or prev_ask <= 0:
                    continue
                prev_mid = (prev_bid + prev_ask) / 2.0

                price_move = mid - prev_mid
                if abs(price_move) < 0.01:
                    continue

                # Follow the volume-price direction
                if price_move > 0:
                    side = "yes"
                    entry_price_c = int(min(ask, 0.99) * 100)
                else:
                    side = "no"
                    entry_price_c = int(min((1.0 - bid), 0.99) * 100)

                correct = side == result
                if correct:
                    pnl = (100 - entry_price_c) - 14
                else:
                    pnl = -entry_price_c - 7
                trades.append(pnl)

        if len(trades) < 10:
            print(f"  vol>={vol_mult:.1f}x: {len(trades)} trades (too few)")
            continue
        n_t = len(trades)
        wins = sum(1 for t in trades if t > 0)
        total = sum(trades)
        print(f"  vol>={vol_mult:.1f}x: {n_t:>5} trades, "
              f"{wins/n_t:.1%} WR, ${total/100:>+8.2f} "
              f"(avg ${total/n_t/100:>+.3f})")

    # ── Strategy 5: Late-Market Conviction (the hybrid) ──
    # Buy when price is moving decisively toward 0 or 1 in the last
    # third of the market, WITH volume confirmation.
    print(f"\n{'='*60}")
    print("STRATEGY 5: LATE CONVICTION (price+volume+time alignment)")
    print(f"{'='*60}")

    for conviction_th in [0.65, 0.70, 0.75, 0.80]:
        for min_move in [0.02, 0.03, 0.05]:
            trades = []
            for mkt in test_markets:
                ticker, result = mkt[0], mkt[1]
                candles = conn.execute(
                    "SELECT * FROM candles WHERE market_ticker = ? ORDER BY end_period_ts",
                    (ticker,)
                ).fetchall()
                candles = [dict(c) for c in candles]
                n = len(candles)

                # Only trade in the last third (60-85% through)
                for check_pct in [0.60, 0.70, 0.80]:
                    check_idx = int(n * check_pct)
                    if check_idx < 5 or check_idx >= n - 1:
                        continue

                    c = candles[check_idx]
                    bid = float(c.get("bid_close") or 0)
                    ask = float(c.get("ask_close") or 0)
                    if bid > 1.5: bid /= 100
                    if ask > 1.5: ask /= 100
                    if bid <= 0 or ask <= 0:
                        continue
                    mid = (bid + ask) / 2.0
                    spread = ask - bid

                    # Must be moving — compare to 3 candles ago
                    prev_c = candles[max(0, check_idx - 3)]
                    pb = float(prev_c.get("bid_close") or 0)
                    pa = float(prev_c.get("ask_close") or 0)
                    if pb > 1.5: pb /= 100
                    if pa > 1.5: pa /= 100
                    if pb <= 0 or pa <= 0:
                        continue
                    prev_mid = (pb + pa) / 2.0
                    move = mid - prev_mid

                    if abs(move) < min_move:
                        continue

                    # Must have conviction price (far from 50%)
                    if mid > conviction_th and move > 0:
                        # High price + rising → strong YES conviction
                        side = "yes"
                        entry_price_c = int(min(ask, 0.99) * 100)
                    elif mid < (1.0 - conviction_th) and move < 0:
                        # Low price + falling → strong NO conviction
                        side = "no"
                        entry_price_c = int(min((1.0 - bid), 0.99) * 100)
                    else:
                        continue

                    # Fee check: don't buy contracts that are too expensive
                    if entry_price_c > 90 or entry_price_c < 10:
                        continue

                    correct = side == result
                    if correct:
                        pnl = (100 - entry_price_c) - 14
                    else:
                        pnl = -entry_price_c - 7
                    trades.append({"pnl": pnl, "correct": correct,
                                   "entry": entry_price_c, "mid": mid})

            if len(trades) < 20:
                continue
            n_t = len(trades)
            wins = sum(1 for t in trades if t["correct"])
            total = sum(t["pnl"] for t in trades)
            avg_entry = sum(t["entry"] for t in trades) / n_t
            print(f"  conv={conviction_th:.2f} move>={min_move:.2f}: "
                  f"{n_t:>5} trades, {wins/n_t:.1%} WR, "
                  f"${total/100:>+8.2f} (avg entry={avg_entry:.0f}¢, "
                  f"avg ${total/n_t/100:>+.3f})")

    # ── Strategy 6: Early contrarian (buy when price is near 50%, let it resolve) ──
    print(f"\n{'='*60}")
    print("STRATEGY 6: EARLY CONTRARIAN (buy uncertain markets cheap)")
    print(f"{'='*60}")

    for entry_frac in [0.20, 0.30, 0.40]:
        for price_range in [(0.40, 0.60), (0.35, 0.65), (0.30, 0.70)]:
            trades = []
            for mkt in test_markets:
                ticker, result = mkt[0], mkt[1]
                candles = conn.execute(
                    "SELECT * FROM candles WHERE market_ticker = ? ORDER BY end_period_ts",
                    (ticker,)
                ).fetchall()
                candles = [dict(c) for c in candles]
                n = len(candles)
                entry_idx = int(n * entry_frac)
                if entry_idx < 2 or entry_idx >= n:
                    continue

                c = candles[entry_idx]
                bid = float(c.get("bid_close") or 0)
                ask = float(c.get("ask_close") or 0)
                if bid > 1.5: bid /= 100
                if ask > 1.5: ask /= 100
                if bid <= 0 or ask <= 0:
                    continue
                mid = (bid + ask) / 2.0

                if not (price_range[0] <= mid <= price_range[1]):
                    continue

                # Slight directional bias: which side of 50% is price on?
                if mid >= 0.50:
                    side = "yes"
                    entry_price_c = int(min(ask, 0.99) * 100)
                else:
                    side = "no"
                    entry_price_c = int(min((1.0 - bid), 0.99) * 100)

                correct = side == result
                if correct:
                    pnl = (100 - entry_price_c) - 14
                else:
                    pnl = -entry_price_c - 7
                trades.append(pnl)

            if len(trades) < 20:
                continue
            n_t = len(trades)
            wins = sum(1 for t in trades if t > 0)
            total = sum(trades)
            print(f"  entry@{entry_frac:.0%} price={price_range[0]:.2f}-{price_range[1]:.2f}: "
                  f"{n_t:>5} trades, {wins/n_t:.1%} WR, "
                  f"${total/100:>+8.2f} (avg ${total/n_t/100:>+.3f})")

    conn.close()
    print(f"\n{'='*60}")
    print("DONE — look for strategies with positive PnL and >52% WR")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
