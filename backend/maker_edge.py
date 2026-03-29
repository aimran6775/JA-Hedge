#!/usr/bin/env python3
"""
Final edge analysis: Can MAKER ORDERS (0¢ fee) unlock profitability?

Kalshi fees:
  - Taker: 7¢/side (14¢ round-trip)
  - Maker: 0¢/side (0¢ round-trip!)

If we place LIMIT orders instead of market orders, we pay 0 fees.
The tradeoff: worse fill rates. But with 0 fees, the math changes completely.

Also check: can we exit early (sell before settlement) to capture
price moves instead of holding to settlement?
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

    # ── Breakeven WR at different fee structures ──
    print(f"\n{'='*60}")
    print("BREAKEVEN WR: Taker (14¢) vs Maker (0¢) vs Hybrid (7¢)")
    print(f"{'='*60}")
    print(f"  {'Price':>5} | {'Taker BE':>10} | {'Hybrid BE':>10} | {'Maker BE':>10} | {'YES Base Rate':>14}")

    # Precompute base rates at each price level
    buckets = {}
    for mkt in test_markets:
        ticker, result = mkt[0], mkt[1]
        candles = conn.execute(
            "SELECT * FROM candles WHERE market_ticker=? ORDER BY end_period_ts",
            (ticker,)
        ).fetchall()
        candles = [dict(c) for c in candles]
        n = len(candles)
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
            bucket = round(mid * 20) / 20
            if bucket not in buckets:
                buckets[bucket] = [0, 0]
            buckets[bucket][1] += 1
            if result == "yes":
                buckets[bucket][0] += 1

    for price_c in range(20, 85, 5):
        p = price_c / 100.0
        bucket = round(p * 20) / 20
        base_rate = buckets.get(bucket, [0, 0])
        br = base_rate[0] / max(base_rate[1], 1) if base_rate[1] > 20 else None

        # Taker: 14¢ round-trip
        win_taker = (100 - price_c) - 14
        lose_taker = price_c + 7
        be_taker = lose_taker / (win_taker + lose_taker) if win_taker > 0 else 1.0

        # Hybrid: maker buy (0), taker sell (7¢) or hold to settlement (0)
        win_hybrid = (100 - price_c) - 7
        lose_hybrid = price_c
        be_hybrid = lose_hybrid / (win_hybrid + lose_hybrid) if win_hybrid > 0 else 1.0

        # Pure maker: 0¢
        win_maker = 100 - price_c
        lose_maker = price_c
        be_maker = lose_maker / (win_maker + lose_maker) if win_maker > 0 else 1.0

        br_str = f"{br:.1%}" if br else "n/a"
        profitable_taker = "✅" if br and br > be_taker else "❌"
        profitable_hybrid = "✅" if br and br > be_hybrid else "❌"
        profitable_maker = "✅" if br and br > be_maker else "❌"

        print(f"  {price_c:>4}¢ | {be_taker:>8.1%} {profitable_taker} | "
              f"{be_hybrid:>8.1%} {profitable_hybrid} | "
              f"{be_maker:>8.1%} {profitable_maker} | {br_str:>14}")

    # ── Simulate maker-order strategy ──
    print(f"\n{'='*60}")
    print("MAKER ORDER SIMULATION (0¢ buy fee, hold to settlement)")
    print(f"{'='*60}")
    print("  (Assumes 100% fill rate — real fill rate will be lower)")

    # Strategy: Buy at mid-price via limit order, hold to settlement
    # This is the simplest possible strategy — just follow the market
    for entry_pct in [0.30, 0.50, 0.70]:
        for price_lo, price_hi in [(0.30, 0.45), (0.55, 0.70), (0.60, 0.75), (0.35, 0.65)]:
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

                if mid < price_lo or mid > price_hi:
                    continue

                # As maker, buy at the bid (not ask) — 0 fee
                if mid >= 0.50:
                    # Buy YES at bid
                    side = "yes"
                    entry_price_c = int(bid * 100)
                else:
                    # Buy NO at bid (equivalent to selling YES at ask)
                    side = "no"
                    entry_price_c = int((1.0 - ask) * 100)

                if entry_price_c <= 0 or entry_price_c >= 100:
                    continue

                correct = side == result
                if correct:
                    # Win: payout = 100¢, no fees
                    pnl = 100 - entry_price_c
                else:
                    # Lose: just the cost, no fees
                    pnl = -entry_price_c

                trades.append({"pnl": pnl, "correct": correct,
                               "entry": entry_price_c, "mid": mid})

            if len(trades) < 20:
                continue
            n_t = len(trades)
            wins = sum(1 for t in trades if t["correct"])
            pnl = sum(t["pnl"] for t in trades)
            avg_entry = sum(t["entry"] for t in trades) / n_t
            print(f"  entry@{entry_pct:.0%} price={price_lo:.2f}-{price_hi:.2f}: "
                  f"{n_t:>5} trades, {wins/n_t:.1%} WR, "
                  f"${pnl/100:>+8.2f} (avg entry={avg_entry:.0f}¢, "
                  f"avg ${pnl/n_t/100:>+.3f})")

    # ── Simulate the mispricing exploitation with maker orders ──
    print(f"\n{'='*60}")
    print("MISPRICING EXPLOITATION (maker orders, target mispricings)")
    print(f"{'='*60}")
    print("  Target: buy when market is systematically wrong")

    # Known mispricings from base rate analysis:
    # 0.35: YES wins 41% (6% underpriced YES)
    # 0.70: YES wins 75.8% (5.8% underpriced YES)
    # 0.50: YES wins 45.9% (4.1% overpriced YES, i.e. NO is underpriced)
    # 0.20: YES wins 16.1% (3.9% overpriced YES, i.e. NO is underpriced)

    for entry_pct in [0.30, 0.50, 0.70]:
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

            side = None
            # Exploit YES underpricing at 30-40¢
            if 0.30 <= mid <= 0.42:
                side = "yes"
                entry_price_c = int(bid * 100)  # maker: buy at bid
            # Exploit YES underpricing at 65-80¢
            elif 0.65 <= mid <= 0.82:
                side = "yes"
                entry_price_c = int(bid * 100)
            # Exploit NO underpricing at 45-55¢
            elif 0.45 <= mid <= 0.55:
                side = "no"
                entry_price_c = int((1.0 - ask) * 100)  # maker buy NO
            # Exploit NO underpricing at 15-25¢
            elif 0.15 <= mid <= 0.25:
                side = "no"
                entry_price_c = int((1.0 - ask) * 100)

            if side is None:
                continue
            if entry_price_c <= 0 or entry_price_c >= 100:
                continue

            correct = side == result
            if correct:
                pnl = 100 - entry_price_c  # 0 fees as maker
            else:
                pnl = -entry_price_c
            trades.append({"pnl": pnl, "correct": correct,
                           "entry": entry_price_c, "side": side, "mid": mid})

        if len(trades) < 10:
            print(f"  entry@{entry_pct:.0%}: {len(trades)} trades")
            continue
        n_t = len(trades)
        wins = sum(1 for t in trades if t["correct"])
        pnl = sum(t["pnl"] for t in trades)

        # Break down by side
        yes_trades = [t for t in trades if t["side"] == "yes"]
        no_trades = [t for t in trades if t["side"] == "no"]
        y_wins = sum(1 for t in yes_trades if t["correct"])
        n_wins = sum(1 for t in no_trades if t["correct"])
        y_pnl = sum(t["pnl"] for t in yes_trades)
        n_pnl = sum(t["pnl"] for t in no_trades)

        print(f"  entry@{entry_pct:.0%}: {n_t:>5} trades, {wins/n_t:.1%} WR, "
              f"${pnl/100:>+8.2f}")
        if yes_trades:
            print(f"    YES: {len(yes_trades)} trades, {y_wins/len(yes_trades):.1%} WR, ${y_pnl/100:>+.2f}")
        if no_trades:
            print(f"     NO: {len(no_trades)} trades, {n_wins/len(no_trades):.1%} WR, ${n_pnl/100:>+.2f}")

    # ── What about EARLY EXIT (buy early, sell at profit before settlement)? ──
    print(f"\n{'='*60}")
    print("EARLY EXIT STRATEGY (buy early, sell when price moves)")
    print("(Maker buy, taker sell = 7¢ total fee)")
    print(f"{'='*60}")

    for entry_pct in [0.20, 0.30, 0.40]:
        for exit_pct in [0.60, 0.70, 0.80]:
            if exit_pct <= entry_pct:
                continue
            for target_profit_c in [5, 10, 15]:
                trades = []
                for mkt in test_markets:
                    ticker, result = mkt[0], mkt[1]
                    candles = conn.execute(
                        "SELECT * FROM candles WHERE market_ticker=? ORDER BY end_period_ts",
                        (ticker,)
                    ).fetchall()
                    candles = [dict(c) for c in candles]
                    n = len(candles)
                    entry_idx = int(n * entry_pct)
                    exit_idx = int(n * exit_pct)
                    if entry_idx < 1 or exit_idx >= n or exit_idx <= entry_idx:
                        continue

                    # Entry
                    ce = candles[entry_idx]
                    bid_e = float(ce.get("bid_close") or 0)
                    ask_e = float(ce.get("ask_close") or 0)
                    if bid_e > 1.5: bid_e /= 100
                    if ask_e > 1.5: ask_e /= 100
                    if bid_e <= 0 or ask_e <= 0:
                        continue
                    mid_e = (bid_e + ask_e) / 2.0

                    # Exit
                    cx = candles[exit_idx]
                    bid_x = float(cx.get("bid_close") or 0)
                    ask_x = float(cx.get("ask_close") or 0)
                    if bid_x > 1.5: bid_x /= 100
                    if ask_x > 1.5: ask_x /= 100
                    if bid_x <= 0 or ask_x <= 0:
                        continue
                    mid_x = (bid_x + ask_x) / 2.0

                    # Only trade mid-range
                    if mid_e < 0.30 or mid_e > 0.70:
                        continue

                    # Decide direction based on slight trend
                    if mid_e >= 0.50:
                        # Buy YES at bid (maker)
                        buy_price_c = int(bid_e * 100)
                        sell_price_c = int(bid_x * 100)  # sell at bid (taker)
                    else:
                        # Buy NO
                        buy_price_c = int((1.0 - ask_e) * 100)
                        sell_price_c = int((1.0 - ask_x) * 100)

                    if buy_price_c <= 0:
                        continue

                    # P&L: sell price - buy price - 7¢ (sell taker fee only, maker buy is free)
                    price_pnl = sell_price_c - buy_price_c - 7

                    # Only take the trade if there was enough price movement
                    if price_pnl >= target_profit_c:
                        trades.append({"pnl": price_pnl, "type": "profit_exit"})
                    elif price_pnl < -target_profit_c:
                        # Stop loss
                        trades.append({"pnl": price_pnl, "type": "stop_loss"})
                    # else: no trade (didn't move enough)

                if len(trades) < 20:
                    continue
                n_t = len(trades)
                profits = [t for t in trades if t["type"] == "profit_exit"]
                stops = [t for t in trades if t["type"] == "stop_loss"]
                total_pnl = sum(t["pnl"] for t in trades)
                print(f"  buy@{entry_pct:.0%} sell@{exit_pct:.0%} target={target_profit_c}¢: "
                      f"{n_t:>4} trades ({len(profits)} wins, {len(stops)} stops), "
                      f"${total_pnl/100:>+7.2f}")

    conn.close()


if __name__ == "__main__":
    main()
