#!/usr/bin/env python3
"""
Deep-dive into WHY high-WR strategies still lose money.
Also explore if there's any edge with MID-RANGE entries where
the payout ratio is better (buy at 50c, win 50c vs buy at 85c win 15c).
"""
import sys
import numpy as np

sys.path.insert(0, ".")

from app.frankenstein.historical import HistoricalHarvester


def main():
    conn = HistoricalHarvester.get_db()

    markets = conn.execute("""
        SELECT m.ticker, m.result, m.series_ticker
        FROM markets m
        JOIN candles c ON c.market_ticker = m.ticker
        WHERE m.result IS NOT NULL
        GROUP BY m.ticker
        HAVING COUNT(*) >= 10
        ORDER BY m.close_time ASC
    """).fetchall()

    n_test = int(len(markets) * 0.20)
    test_markets = markets[-n_test:]
    print(f"Test markets: {len(test_markets)}")

    # ── Understand the P&L math ──
    print(f"\n{'='*60}")
    print("P&L MATH: Why 85% WR loses money at 85¢ entry")
    print(f"{'='*60}")
    for entry_c in [50, 60, 70, 80, 85, 90]:
        win_pnl = (100 - entry_c) - 14  # win payout minus cost minus round-trip fees
        lose_pnl = -entry_c - 7  # lose cost plus buy fee
        breakeven_wr = abs(lose_pnl) / (win_pnl + abs(lose_pnl)) if win_pnl > 0 else 1.0
        print(f"  Entry {entry_c}¢: win=${win_pnl/100:+.2f}, lose=${lose_pnl/100:+.2f}, "
              f"breakeven WR={breakeven_wr:.1%}")

    # The key insight: at 85¢ entry, you need 93% WR to break even!
    # Our best strategies only have 88% WR at 85¢. That's LOSING.
    # 
    # The ONLY way to profit is:
    # 1. Find mid-range entries (40-60¢) where breakeven is 57-64%
    # 2. Have a genuine information advantage at those price levels

    # ── Strategy: Mid-price technical patterns ──
    # Look for markets where price is 35-65¢ and there's a clear technical signal
    print(f"\n{'='*60}")
    print("STRATEGY: MID-PRICE TECHNICAL SIGNALS")
    print("(the only price range where fees don't kill you)")
    print(f"{'='*60}")

    # Sub-strategy A: RSI-like signal in mid-range
    for entry_pct in [0.40, 0.50, 0.60]:
        for consec_up in [2, 3, 4]:
            trades = []
            for mkt in test_markets:
                ticker, result = mkt[0], mkt[1]
                candles = conn.execute(
                    "SELECT * FROM candles WHERE market_ticker=? ORDER BY end_period_ts",
                    (ticker,)
                ).fetchall()
                candles = [dict(c) for c in candles]
                n = len(candles)
                check_idx = int(n * entry_pct)
                if check_idx < consec_up + 1 or check_idx >= n:
                    continue

                # Get prices
                prices = []
                for i in range(max(0, check_idx - consec_up - 1), check_idx + 1):
                    c = candles[i]
                    bid = float(c.get("bid_close") or 0)
                    ask = float(c.get("ask_close") or 0)
                    if bid > 1.5: bid /= 100
                    if ask > 1.5: ask /= 100
                    if bid > 0 and ask > 0:
                        prices.append((bid + ask) / 2.0)

                if len(prices) < consec_up + 1:
                    continue

                mid = prices[-1]
                if mid < 0.35 or mid > 0.65:
                    continue

                # Check for consecutive same-direction moves
                up_count = 0
                down_count = 0
                for j in range(1, len(prices)):
                    if prices[j] > prices[j-1] + 0.005:
                        up_count += 1
                        down_count = 0
                    elif prices[j] < prices[j-1] - 0.005:
                        down_count += 1
                        up_count = 0
                    else:
                        up_count = 0
                        down_count = 0

                if up_count >= consec_up:
                    side = "yes"  # momentum: follow the trend
                elif down_count >= consec_up:
                    side = "no"
                else:
                    continue

                entry_c = candles[check_idx]
                bid = float(entry_c.get("bid_close") or 0)
                ask = float(entry_c.get("ask_close") or 0)
                if bid > 1.5: bid /= 100
                if ask > 1.5: ask /= 100

                if side == "yes":
                    price_c = int(min(ask, 0.99) * 100)
                else:
                    price_c = int(min((1.0 - bid), 0.99) * 100)

                if price_c > 65 or price_c < 35:
                    continue

                correct = side == result
                if correct:
                    pnl = (100 - price_c) - 14
                else:
                    pnl = -price_c - 7
                trades.append({"pnl": pnl, "correct": correct, "price": price_c})

            if len(trades) < 15:
                continue
            n_t = len(trades)
            wins = sum(1 for t in trades if t["correct"])
            pnl = sum(t["pnl"] for t in trades)
            avg_price = sum(t["price"] for t in trades) / n_t
            print(f"  entry@{entry_pct:.0%} consec={consec_up}: "
                  f"{n_t:>4} trades, {wins/n_t:.1%} WR, "
                  f"${pnl/100:>+7.2f} (avg_entry={avg_price:.0f}¢)")

    # ── Sub-strategy B: Price crosses 50% (momentum through the middle) ──
    print(f"\n  Price-cross-50% signals:")
    for lookback in [2, 3]:
        trades = []
        for mkt in test_markets:
            ticker, result = mkt[0], mkt[1]
            candles = conn.execute(
                "SELECT * FROM candles WHERE market_ticker=? ORDER BY end_period_ts",
                (ticker,)
            ).fetchall()
            candles = [dict(c) for c in candles]
            n = len(candles)

            for check_pct in [0.40, 0.50, 0.60]:
                check_idx = int(n * check_pct)
                if check_idx < lookback + 1 or check_idx >= n:
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

                if len(prices) < lookback + 1:
                    continue

                old_price = prices[0]
                new_price = prices[-1]

                # Crossed above 50%
                if old_price < 0.50 and new_price > 0.50 and new_price < 0.65:
                    side = "yes"
                # Crossed below 50%
                elif old_price > 0.50 and new_price < 0.50 and new_price > 0.35:
                    side = "no"
                else:
                    continue

                entry_c = candles[check_idx]
                bid = float(entry_c.get("bid_close") or 0)
                ask = float(entry_c.get("ask_close") or 0)
                if bid > 1.5: bid /= 100
                if ask > 1.5: ask /= 100

                if side == "yes":
                    price_c = int(min(ask, 0.99) * 100)
                else:
                    price_c = int(min((1.0 - bid), 0.99) * 100)

                if price_c > 65 or price_c < 35:
                    continue

                correct = side == result
                if correct:
                    pnl = (100 - price_c) - 14
                else:
                    pnl = -price_c - 7
                trades.append({"pnl": pnl, "correct": correct, "price": price_c})

        if len(trades) < 10:
            print(f"    lb={lookback}: {len(trades)} trades (too few)")
            continue
        n_t = len(trades)
        wins = sum(1 for t in trades if t["correct"])
        pnl = sum(t["pnl"] for t in trades)
        print(f"    lb={lookback}: {n_t:>4} trades, {wins/n_t:.1%} WR, "
              f"${pnl/100:>+7.2f}")

    # ── The REAL question: what does it take to beat 14¢ fees? ──
    print(f"\n{'='*60}")
    print("REALITY CHECK: What WR is needed at each entry price?")
    print(f"{'='*60}")
    print("Entry¢ | Win$  | Lose$ | Break-even WR | Actual WR needed for +EV")
    for ec in range(30, 95, 5):
        win_pnl = (100 - ec) - 14
        lose_pnl = ec + 7
        be_wr = lose_pnl / (win_pnl + lose_pnl)
        target = be_wr + 0.02  # need 2% above breakeven to be meaningful
        print(f"  {ec:>3}¢  | {win_pnl/100:>+.2f} | {-lose_pnl/100:>+.2f} | "
              f"{be_wr:>12.1%}  | {target:.1%}")

    # ── Market efficiency check: what's the base rate by price bucket? ──
    print(f"\n{'='*60}")
    print("BASE RATE: How often does YES win at each price level?")
    print(f"(If base rate = price, markets are perfectly efficient)")
    print(f"{'='*60}")

    buckets = {}  # price_bucket -> (yes_count, total_count)
    for mkt in test_markets:
        ticker, result = mkt[0], mkt[1]
        candles = conn.execute(
            "SELECT * FROM candles WHERE market_ticker=? ORDER BY end_period_ts",
            (ticker,)
        ).fetchall()
        candles = [dict(c) for c in candles]
        n = len(candles)

        # Check at multiple time points
        for check_pct in [0.30, 0.50, 0.70]:
            check_idx = int(n * check_pct)
            if check_idx >= n or check_idx < 1:
                continue
            c = candles[check_idx]
            bid = float(c.get("bid_close") or 0)
            ask = float(c.get("ask_close") or 0)
            if bid > 1.5: bid /= 100
            if ask > 1.5: ask /= 100
            if bid <= 0 or ask <= 0:
                continue
            mid = (bid + ask) / 2.0
            bucket = round(mid * 20) / 20  # 5% buckets
            if bucket not in buckets:
                buckets[bucket] = [0, 0]
            buckets[bucket][1] += 1
            if result == "yes":
                buckets[bucket][0] += 1

    print(f"  {'Price':>6} | {'YES WR':>8} | {'Samples':>8} | {'Calibration Error':>18}")
    for price in sorted(buckets.keys()):
        yes_c, total = buckets[price]
        if total < 20:
            continue
        wr = yes_c / total
        cal_err = wr - price
        marker = "<<< MISPRICING" if abs(cal_err) > 0.03 else ""
        print(f"  {price:>5.2f} | {wr:>7.1%} | {total:>8} | "
              f"{cal_err:>+17.3f} {marker}")

    conn.close()


if __name__ == "__main__":
    main()
