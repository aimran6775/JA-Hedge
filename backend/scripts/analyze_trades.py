#!/usr/bin/env python3
"""Analyze trade reasoning from Frankenstein's production instance."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read())

print("=" * 70)
print("FRANKENSTEIN TRADE ANALYSIS")
print("=" * 70)

# Status
status = fetch("/api/frankenstein/status")
print(f"\nModel trained: {not status.get('learning_mode', True)}")
print(f"Learning mode: {status.get('learning_mode')}")
print(f"Real trades: {status.get('real_trades')}")
print(f"Total executed: {status.get('total_trades_executed')}")
print(f"Total scans: {status.get('total_scans')}")

mem = status.get("memory", {})
print(f"\nMemory: {mem.get('total_recorded')} recorded, {mem.get('total_resolved')} resolved, {mem.get('pending')} pending")
print(f"Outcomes: {mem.get('outcomes', {})}")

# Rejections (current model view)
rej = fetch("/api/frankenstein/debug/rejections")
print(f"\n{'=' * 70}")
print(f"CURRENT PIPELINE STATE")
print(f"{'=' * 70}")
print(f"Active markets: {rej['total_active']}")
print(f"Pre-filtered: {rej['total_pre_filtered']}")
print(f"Model trained: {rej['model_trained']}")
print(f"Learning mode: {rej['is_learning_mode']}")

print(f"\n--- TOP 8 CANDIDATES (what model evaluates) ---")
for c in rej.get("candidates", [])[:8]:
    p = c.get("prediction", {})
    m = c.get("market", {})
    g = c.get("confidence_grade", {})
    factors = g.get("factors", {})
    rej_reason = c.get("rejection_reason", "none")
    print(f"\n  {c['ticker']}")
    print(f"    Title: {c.get('title', '?')}")
    print(f"    Prediction: side={p.get('side')}, edge={p.get('edge'):.4f}, "
          f"confidence={p.get('confidence'):.2f}, prob={p.get('prob'):.4f}")
    print(f"    Market: mid={m.get('midpoint')}, spread={m.get('spread')}, "
          f"vol={m.get('volume')}, price={m.get('price_cents')}¢")
    print(f"    Grade: {g.get('grade')} (score={g.get('score')}), trade={g.get('should_trade')}")
    for fname, fdata in factors.items():
        print(f"      {fname}: {fdata.get('score')}/100 → {fdata.get('reason', '')[:80]}")
    print(f"    Rejection: {rej_reason}")

# Recent memory
try:
    trades = fetch("/api/frankenstein/memory/recent?limit=15")
    print(f"\n{'=' * 70}")
    print(f"RECENT TRADE MEMORY ({len(trades)} entries)")
    print(f"{'=' * 70}")
    for t in trades:
        print(f"\n  Trade: {t['trade_id']}")
        print(f"    Ticker: {t['ticker']}")
        print(f"    Action: {t['action']} {t['side_executed']} x{t['count']} @ {t['price_cents']}¢")
        print(f"    Model: {t['model_version']}, conf={t['confidence']:.2f}, edge={t['edge']:.4f}")
        print(f"    Predicted: side={t['predicted_side']}, prob={t['predicted_prob']:.4f}")
        print(f"    Cost: {t['total_cost_cents']}¢, fees={t['fees_cents']}¢")
        print(f"    Outcome: {t['outcome']}, PnL={t['pnl_cents']}¢, hold={t['hold_time_seconds']:.1f}s")
        # Key features
        fn = t.get("feature_names", [])
        fv = t.get("features", [])
        feat_dict = dict(zip(fn, fv))
        print(f"    Features: mid={feat_dict.get('midpoint', '?'):.3f}, "
              f"spread={feat_dict.get('spread', '?'):.3f}, "
              f"vol={feat_dict.get('volume', '?'):.0f}, "
              f"OI={feat_dict.get('open_interest', '?'):.0f}, "
              f"hours_exp={feat_dict.get('hours_to_expiry', '?'):.1f}")
        print(f"    Signals: momentum={feat_dict.get('momentum_10', 0):.4f}, "
              f"RSI={feat_dict.get('rsi_14', 50):.1f}, "
              f"MACD={feat_dict.get('macd', 0):.4f}, "
              f"book_imbal={feat_dict.get('book_imbalance', 0):.3f}")
except Exception as e:
    print(f"Error fetching trades: {e}")

# Current positions
try:
    portfolio = fetch("/api/portfolio")
    positions = portfolio.get("positions", [])
    print(f"\n{'=' * 70}")
    print(f"CURRENT POSITIONS ({len(positions)})")
    print(f"{'=' * 70}")
    for pos in positions[:10]:
        print(f"  {pos.get('ticker', '?')}: qty={pos.get('position', '?')}, "
              f"avg_price={pos.get('average_price', '?')}")
except Exception as e:
    print(f"Portfolio error: {e}")
