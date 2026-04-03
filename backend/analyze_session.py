#!/usr/bin/env python3
"""Analyze this session's trading performance."""
import json, time
from collections import Counter, defaultdict

with open("data/frankenstein_memory.json") as f:
    d = json.load(f)

trades = d.get("trades", [])
print(f"Total trades in memory: {len(trades)}")

# All-time outcomes
outcomes_all = Counter(t.get("outcome", "?") for t in trades)
wins_all = outcomes_all.get("win", 0)
losses_all = outcomes_all.get("loss", 0)
print(f"\n=== ALL-TIME ===")
print(f"Outcomes: {dict(outcomes_all)}")
if wins_all + losses_all > 0:
    print(f"Win rate: {wins_all/(wins_all+losses_all):.1%} ({wins_all}W / {losses_all}L)")

# This session (last ~22 hours)
cutoff = time.time() - 22 * 3600
session = [t for t in trades if t.get("timestamp", 0) > cutoff]
print(f"\n=== THIS SESSION ({len(session)} trades) ===")

outcomes = Counter(t.get("outcome", "?") for t in session)
print(f"Outcomes: {dict(outcomes)}")
wins = outcomes.get("win", 0)
losses = outcomes.get("loss", 0)
resolved = wins + losses
print(f"Resolved: {resolved}  Wins: {wins}  Losses: {losses}")
if resolved > 0:
    print(f"Win rate: {wins/resolved:.1%}")

# What tickers?
tickers = Counter(t.get("ticker", "?").split("-")[0] for t in session)
print(f"\nTickers traded:")
for tk, cnt in tickers.most_common(10):
    print(f"  {tk}: {cnt} trades")

# Category breakdown
cat_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "expired": 0, "pending": 0, "breakeven": 0, "pnl": 0, "count": 0})
for t in session:
    cat = t.get("category", "unknown")
    outcome = t.get("outcome", "?")
    pnl = t.get("pnl_cents", 0) or 0
    cat_stats[cat]["pnl"] += pnl
    cat_stats[cat]["count"] += 1
    if outcome == "win":
        cat_stats[cat]["wins"] += 1
    elif outcome == "loss":
        cat_stats[cat]["losses"] += 1
    elif outcome == "expired":
        cat_stats[cat]["expired"] += 1
    elif outcome == "breakeven":
        cat_stats[cat]["breakeven"] += 1
    elif outcome == "pending":
        cat_stats[cat]["pending"] += 1

print(f"\nCategory breakdown:")
for cat, s in sorted(cat_stats.items()):
    total = s["wins"] + s["losses"]
    wr = f"{s['wins']/total:.0%}" if total > 0 else "n/a"
    print(f"  {cat:12s}: {s['count']:3d} trades  W:{s['wins']:2d} L:{s['losses']:2d} E:{s['expired']:2d} B:{s['breakeven']:2d} P:{s['pending']:2d}  WR:{wr:>4s}  PnL:{s['pnl']:>6d}c")

# Show last 10 resolved trades
print(f"\nLast 10 resolved trades:")
resolved_trades = [t for t in session if t.get("outcome") in ("win", "loss")]
for t in resolved_trades[-10:]:
    ticker = t.get("ticker", "?")
    side = t.get("predicted_side", "?")
    outcome = t.get("outcome", "?")
    pnl = t.get("pnl_cents", 0) or 0
    cost = t.get("total_cost_cents", 0)
    prob = t.get("predicted_prob", 0)
    print(f"  {ticker:45s} pred={side:3s}@{prob:.0%}  {outcome:4s}  pnl={pnl:>5d}c  cost={cost:>4d}c")
