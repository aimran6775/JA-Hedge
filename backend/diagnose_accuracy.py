#!/usr/bin/env python3
"""Deep diagnosis: WHY is accuracy so low? Analyze actual trade data."""
import json, time
from collections import Counter, defaultdict

with open("data/frankenstein_memory.json") as f:
    d = json.load(f)

trades = d.get("trades", [])
print(f"Total trades in memory: {len(trades)}\n")

# ── 1. Outcome breakdown ─────────────────────────────────────────
outcomes = Counter(t.get("outcome", "?") for t in trades)
print("=== 1. OUTCOME BREAKDOWN ===")
for k, v in outcomes.most_common():
    print(f"  {k:12s}: {v:4d} ({v/len(trades)*100:.1f}%)")

resolved = [t for t in trades if t.get("outcome") in ("win", "loss")]
wins = [t for t in resolved if t["outcome"] == "win"]
losses = [t for t in resolved if t["outcome"] == "loss"]
print(f"\n  Resolved: {len(resolved)}  →  W:{len(wins)} L:{len(losses)}  WR:{len(wins)/max(1,len(resolved)):.1%}")

# ── 2. Where are losses coming from? ─────────────────────────────
print("\n=== 2. LOSS ANALYSIS (what side did we pick, what happened?) ===")
side_result = Counter()
for t in resolved:
    side = t.get("predicted_side", "?")
    result = t.get("market_result", "?")
    outcome = t["outcome"]
    side_result[(side, result, outcome)] += 1

for (side, result, outcome), count in side_result.most_common():
    print(f"  predicted={side:3s}  actual={result:3s}  → {outcome:4s}  x{count}")

# ── 3. Probability calibration: what prob did we predict vs what happened? ──
print("\n=== 3. PREDICTED PROB vs OUTCOME (are probabilities calibrated?) ===")
prob_buckets = defaultdict(lambda: {"total": 0, "yes_happened": 0})
for t in resolved:
    prob = t.get("predicted_prob", 0.5)
    result = t.get("market_result", "?")
    bucket = round(prob * 10) / 10  # bucket by 10%
    prob_buckets[bucket]["total"] += 1
    if result == "yes":
        prob_buckets[bucket]["yes_happened"] += 1

print(f"  {'P(YES)':>8s} {'Count':>6s} {'YES%':>6s} {'Expected':>8s} {'Delta':>6s}")
for bucket in sorted(prob_buckets.keys()):
    s = prob_buckets[bucket]
    actual = s["yes_happened"] / s["total"]
    delta = actual - bucket
    print(f"  {bucket:8.1f} {s['total']:6d} {actual:6.1%} {bucket:8.1%} {delta:+6.1%}")

# ── 4. Edge analysis: what edges did we trade at? ────────────────
print("\n=== 4. EDGE ANALYSIS (what edge did we take?) ===")
edges_win = [abs(t.get("edge", 0)) for t in wins]
edges_loss = [abs(t.get("edge", 0)) for t in losses]
if edges_win:
    print(f"  Win  edges: avg={sum(edges_win)/len(edges_win):.3f} min={min(edges_win):.3f} max={max(edges_win):.3f}")
if edges_loss:
    print(f"  Loss edges: avg={sum(edges_loss)/len(edges_loss):.3f} min={min(edges_loss):.3f} max={max(edges_loss):.3f}")

# Edge buckets
edge_buckets = defaultdict(lambda: {"wins": 0, "losses": 0})
for t in resolved:
    edge = abs(t.get("edge", 0))
    bucket = round(edge * 20) / 20  # 5% buckets
    if t["outcome"] == "win":
        edge_buckets[bucket]["wins"] += 1
    else:
        edge_buckets[bucket]["losses"] += 1

print(f"\n  {'Edge':>6s} {'Wins':>5s} {'Loss':>5s} {'WR':>6s}")
for bucket in sorted(edge_buckets.keys()):
    s = edge_buckets[bucket]
    total = s["wins"] + s["losses"]
    wr = s["wins"] / total if total > 0 else 0
    print(f"  {bucket:6.2f} {s['wins']:5d} {s['losses']:5d} {wr:6.1%}")

# ── 5. Market type analysis: which markets win/lose? ─────────────
print("\n=== 5. MARKET TYPE ANALYSIS ===")
prefix_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "expired": 0, "pnl": 0})
for t in trades:
    ticker = t.get("ticker", "?")
    prefix = ticker.split("-")[0]
    outcome = t.get("outcome", "?")
    pnl = t.get("pnl_cents", 0) or 0
    prefix_stats[prefix]["pnl"] += pnl
    if outcome == "win":
        prefix_stats[prefix]["wins"] += 1
    elif outcome == "loss":
        prefix_stats[prefix]["losses"] += 1
    elif outcome == "expired":
        prefix_stats[prefix]["expired"] += 1

print(f"  {'Prefix':20s} {'W':>4s} {'L':>4s} {'E':>4s} {'WR':>6s} {'PnL':>7s}")
for prefix, s in sorted(prefix_stats.items(), key=lambda x: x[1]["wins"]+x[1]["losses"], reverse=True)[:25]:
    total = s["wins"] + s["losses"]
    wr = f"{s['wins']/total:.0%}" if total > 0 else "n/a"
    print(f"  {prefix:20s} {s['wins']:4d} {s['losses']:4d} {s['expired']:4d} {wr:>6s} {s['pnl']:>7d}c")

# ── 6. Time-to-expiry analysis ───────────────────────────────────
print("\n=== 6. MARKET DURATION ANALYSIS ===")
# Check if markets are 15-min, hourly, daily etc by ticker patterns
duration_stats = defaultdict(lambda: {"wins": 0, "losses": 0, "total": 0})
for t in resolved:
    ticker = t.get("ticker", "?")
    if "15M" in ticker.upper():
        dur = "15-min"
    elif "1H" in ticker.upper() or "60M" in ticker.upper():
        dur = "1-hour"
    elif "4H" in ticker.upper():
        dur = "4-hour"
    elif "24H" in ticker.upper() or "DAILY" in ticker.upper():
        dur = "daily"
    else:
        dur = "other/event"
    duration_stats[dur]["total"] += 1
    if t["outcome"] == "win":
        duration_stats[dur]["wins"] += 1
    else:
        duration_stats[dur]["losses"] += 1

print(f"  {'Duration':15s} {'Wins':>5s} {'Loss':>5s} {'WR':>6s}")
for dur, s in sorted(duration_stats.items()):
    wr = s["wins"] / s["total"] if s["total"] > 0 else 0
    print(f"  {dur:15s} {s['wins']:5d} {s['losses']:5d} {wr:6.1%}")

# ── 7. Heuristic vs trained model ────────────────────────────────
print("\n=== 7. MODEL VERSION ANALYSIS ===")
model_stats = defaultdict(lambda: {"wins": 0, "losses": 0})
for t in resolved:
    ver = t.get("model_version", "unknown")
    if t["outcome"] == "win":
        model_stats[ver]["wins"] += 1
    else:
        model_stats[ver]["losses"] += 1

for ver, s in sorted(model_stats.items()):
    total = s["wins"] + s["losses"]
    wr = s["wins"] / total if total > 0 else 0
    print(f"  {ver:30s}  W:{s['wins']:3d} L:{s['losses']:3d}  WR:{wr:.1%}")

# ── 8. The BIG question: are we predicting NO but YES happens? ──
print("\n=== 8. SIDE PREDICTION ACCURACY ===")
yes_pred = [t for t in resolved if t.get("predicted_side") == "yes"]
no_pred = [t for t in resolved if t.get("predicted_side") == "no"]
yes_correct = sum(1 for t in yes_pred if t["outcome"] == "win")
no_correct = sum(1 for t in no_pred if t["outcome"] == "win")
print(f"  Predicted YES: {len(yes_pred)} trades, {yes_correct} correct ({yes_correct/max(1,len(yes_pred)):.1%})")
print(f"  Predicted NO:  {len(no_pred)} trades, {no_correct} correct ({no_correct/max(1,len(no_pred)):.1%})")

# ── 9. What % of trades expire (never resolved)? ─────────────────
expired = [t for t in trades if t.get("outcome") == "expired"]
pending = [t for t in trades if t.get("outcome") == "pending"]
breakeven = [t for t in trades if t.get("outcome") == "breakeven"]
print(f"\n=== 9. NON-RESOLUTION RATE ===")
print(f"  Expired (48h timeout):   {len(expired)} ({len(expired)/len(trades)*100:.1f}%)")
print(f"  Breakeven (sell/exit):   {len(breakeven)} ({len(breakeven)/len(trades)*100:.1f}%)")
print(f"  Pending (still open):    {len(pending)} ({len(pending)/len(trades)*100:.1f}%)")
print(f"  Actually resolved (W/L): {len(resolved)} ({len(resolved)/len(trades)*100:.1f}%)")

# ── 10. PnL analysis ─────────────────────────────────────────────
print("\n=== 10. PnL ANALYSIS ===")
total_pnl = sum(t.get("pnl_cents", 0) or 0 for t in trades)
win_pnl = sum(t.get("pnl_cents", 0) or 0 for t in wins)
loss_pnl = sum(t.get("pnl_cents", 0) or 0 for t in losses)
avg_win = win_pnl / len(wins) if wins else 0
avg_loss = loss_pnl / len(losses) if losses else 0
print(f"  Total PnL: {total_pnl}c (${total_pnl/100:.2f})")
print(f"  Win PnL:   {win_pnl}c avg {avg_win:.1f}c/trade")
print(f"  Loss PnL:  {loss_pnl}c avg {avg_loss:.1f}c/trade")
if avg_loss != 0:
    print(f"  Win/Loss ratio: {abs(avg_win/avg_loss):.2f}x")
