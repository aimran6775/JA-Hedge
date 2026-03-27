#!/usr/bin/env python3
"""Debug: show exactly what the bot is evaluating and why trades pass/fail."""
import json, urllib.request

BASE = "https://api.frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())

# 1. Current status
st = fetch("/api/frankenstein/status")
print("=" * 70)
print("FRANKENSTEIN STATUS")
print("=" * 70)
print(f"  Uptime:    {st.get('uptime_human','?')}")
print(f"  Scans:     {st['total_scans']}")
print(f"  Signals:   {st['total_signals']}")
print(f"  Executed:  {st['total_trades_executed']}")
print(f"  Rejected:  {st['total_trades_rejected']}")
sp = st.get('strategy',{}).get('current_params',{})
print(f"  min_edge:  {sp.get('min_edge','?')}")
print(f"  min_conf:  {sp.get('min_confidence','?')}")
print(f"  kelly_f:   {sp.get('kelly_fraction','?')}")

sd = st.get('last_scan_debug',{})
print(f"\n  Last scan: {sd.get('candidates','?')} candidates -> {sd.get('trade_candidates','?')} trade -> {sd.get('exec_successes','?')} executed")

# 2. Rejection details
rej = fetch("/api/frankenstein/debug/rejections")
details = rej.get('details', [])
print(f"\n{'=' * 70}")
print(f"CANDIDATE ANALYSIS ({rej.get('total_active','?')} active markets -> {rej.get('total_candidates','?')} passed pre-filter)")
print(f"{'=' * 70}")

if not details:
    # Single top-level record
    pred = rej.get('prediction',{})
    feat = rej.get('features',{})
    sz = rej.get('sizing',{})
    par = rej.get('params',{})
    print(f"\n  Ticker: {rej.get('ticker','?')}")
    print(f"  Title:  {rej.get('title','?')[:90]}")
    print(f"  Side={pred.get('side','?')}, Confidence={pred.get('confidence',0):.3f}, Edge={pred.get('edge',0):.4f}")
    print(f"  Midpoint={feat.get('midpoint','?')}, Spread={feat.get('spread','?')}, Volume={feat.get('volume','?')}")
    print(f"  Kelly={sz.get('kelly','?')}, Count={sz.get('count','?')}, Price={sz.get('price_cents','?')}c")
    print(f"  Params: min_conf={par.get('min_confidence','?')}, min_edge={par.get('min_edge','?')}")
    
    # Diagnose WHY it didn't trade
    conf = pred.get('confidence', 0)
    edge = pred.get('edge', 0)
    kelly = sz.get('kelly', 0)
    print(f"\n  DIAGNOSIS:")
    if conf < par.get('min_confidence', 0.5):
        print(f"    BLOCKED: confidence {conf:.3f} < min {par.get('min_confidence',0.5)}")
    if edge < par.get('min_edge', 0.1):
        print(f"    BLOCKED: edge {edge:.4f} < min {par.get('min_edge',0.1)}")
    if kelly <= 0:
        print(f"    BLOCKED: kelly = {kelly} (no positive expected value)")
else:
    for i, det in enumerate(details[:15]):
        pred = det.get('prediction',{})
        feat = det.get('features',{})
        sz = det.get('sizing',{})
        conf = pred.get('confidence', 0)
        edge = pred.get('edge', 0)
        kelly = sz.get('kelly', 0)
        price = sz.get('price_cents', 0)
        
        print(f"\n--- Candidate {i+1}: {det.get('ticker','?')} ---")
        print(f"  {det.get('title','?')[:90]}")
        print(f"  Side={pred.get('side','?')}, Confidence={conf:.3f}, Edge={edge:.4f}, Prob={pred.get('prob',0):.3f}")
        print(f"  Midpoint={feat.get('midpoint','?')}, Spread={feat.get('spread','?')}, Volume={feat.get('volume','?')}")
        print(f"  Kelly={kelly}, Count={sz.get('count','?')}, Price={price}c")
        
        # Fee analysis
        fee_pct = 14.0 / price if price > 0 else 999
        print(f"  Fee drag: 14c round-trip / {price}c = {fee_pct:.1%}")
        
        # Diagnosis
        reasons = []
        if conf < 0.5:
            reasons.append(f"confidence {conf:.3f} < 0.50")
        if edge < 0.1:
            reasons.append(f"edge {edge:.4f} < 0.10")
        if kelly <= 0:
            reasons.append(f"kelly={kelly} (negative EV)")
        if reasons:
            print(f"  BLOCKED: {'; '.join(reasons)}")
        else:
            print(f"  PASSED all gates -> should execute")

# 3. Check if there are recent trades
try:
    trades = fetch("/api/frankenstein/trades?limit=5")
    recent = trades if isinstance(trades, list) else trades.get('trades', trades.get('recent', []))
    print(f"\n{'=' * 70}")
    print(f"RECENT TRADES: {len(recent)}")
    print(f"{'=' * 70}")
    for t in recent[:5]:
        print(f"  {t.get('ticker','?')} {t.get('side','?')} @ {t.get('price','?')}c conf={t.get('confidence','?')} edge={t.get('edge','?')} -> {t.get('outcome','pending')}")
except:
    print("\n  (No trade history endpoint available)")

print(f"\n{'=' * 70}")
print("SUMMARY")
print("=" * 70)
print(f"The bot scanned {rej.get('total_active','?')} markets.")
print(f"Only {rej.get('total_candidates','?')} passed the pre-filter (volume, spread, expiry).")
print(f"Of those, the issue is likely: edge and confidence are too low because")
print(f"the model is untrained (generation 0) and produces near-random predictions.")
