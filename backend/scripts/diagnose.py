#!/usr/bin/env python3
"""Diagnose why Frankenstein isn't trading."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"ERROR fetching {path}: {e}")
        return {}

print("=" * 60)
print("1. FRANKENSTEIN STATUS")
print("=" * 60)
d = fetch("/api/frankenstein/status")
print(f"  Alive:        {d.get('is_alive')}")
print(f"  Trading:      {d.get('is_trading')}")
print(f"  Paused:       {d.get('is_paused')} ({d.get('pause_reason', '')})")
print(f"  Uptime:       {d.get('uptime_human')}")
print(f"  Total scans:  {d.get('total_scans')}")
print(f"  Total trades: {d.get('total_trades_executed')}")
print(f"  Rejected:     {d.get('total_trades_rejected')}")
print(f"  Daily:        {d.get('daily_trades')}/{d.get('daily_trade_cap')}")
print(f"  Last scan ms: {d.get('last_scan_ms')}")
print(f"  Sports only:  {d.get('sports_only_mode')}")
print(f"  Circuit brk:  {d.get('circuit_breaker_active')}")
print(f"  Generation:   {d.get('generation')}")

ws = d.get("ws_bridge", {})
print(f"  WS bridge:    connected={ws.get('connected')} subs={ws.get('subscriptions')}")

print(f"\n  Last scan debug:")
lsd = d.get("last_scan_debug", {})
for k, v in lsd.items():
    print(f"    {k}: {v}")

sp = d.get("strategy", {}).get("params", {})
print(f"\n  Strategy params:")
for k, v in sp.items():
    print(f"    {k}: {v}")

om = d.get("order_manager", {})
print(f"\n  Order manager:")
for k, v in om.items():
    print(f"    {k}: {v}")

cap = d.get("capital", {})
print(f"\n  Capital:")
for k, v in cap.items():
    print(f"    {k}: {v}")

mem = d.get("memory", {})
print(f"\n  Memory: {mem.get('total_trades', 0)} trades, {mem.get('recent_count', 0)} recent")

print()
print("=" * 60)
print("2. HEALTH CHECK")
print("=" * 60)
h = fetch("/health")
for k, v in h.get("components", {}).items():
    status = "✅" if v in ("ready", "connected", "active", "alive") else "⚠️"
    print(f"  {status} {k}: {v}")

paper = h.get("paper_trading", {})
if paper:
    print(f"\n  Paper trading: balance=${paper.get('balance')} pnl=${paper.get('pnl')} trades={paper.get('total_trades')}")

print()
print("=" * 60)
print("3. INTELLIGENCE SOURCES")
print("=" * 60)
intel = fetch("/api/intelligence/status")
print(f"  Running: {intel.get('running')}")
print(f"  Sources: {intel.get('total_sources')} ({intel.get('healthy_sources')} healthy)")
print(f"  Signals: {intel.get('total_signals_lifetime')} lifetime, {intel.get('signals_last_5min')} last 5min")
for src in intel.get("sources", []):
    icon = "✅" if src.get("healthy") else "❌"
    print(f"  {icon} {src['name']:25s} fetches={src['fetch_count']:3d} signals={src['signal_count']:5d} errors={src['error_count']:3d}")

print()
print("=" * 60)
print("4. SPORTS / REALTIME FEED")
print("=" * 60)
sp = fetch("/api/sports/status")
for k, v in sp.get("components", {}).items():
    print(f"  {k}: {v}")

rf = sp.get("realtime_feed", {})
if rf:
    print(f"\n  Feed: hub_connected={rf.get('hub_connected')} available={rf.get('available')}")
    cache = rf.get("cache", {})
    print(f"  Cache: odds={cache.get('cached_odds')} scores={cache.get('cached_scores')}")
    stats = rf.get("stats", {})
    print(f"  Stats: hub_reads={stats.get('hub_reads')} espn_fetches={stats.get('espn_score_fetches')} consensus={stats.get('consensus_computed')}")

print()
print("=" * 60)
print("5. MARKETS SAMPLE")
print("=" * 60)
try:
    with urllib.request.urlopen(f"{BASE}/api/markets?limit=5&status=active", timeout=15) as r:
        markets = json.loads(r.read())
    print(f"  Total active: {markets.get('total', '?')}")
    for m in markets.get("markets", [])[:5]:
        spread = (m.get("yes_ask", 0) or 0) - (m.get("yes_bid", 0) or 0)
        print(f"  {m['ticker'][:40]:40s} mid={m.get('midpoint','?'):>5} spread={spread:>3} vol={m.get('volume','?')}")
except Exception as e:
    print(f"  Error: {e}")

print()
print("=" * 60)
print("6. PORTFOLIO")
print("=" * 60)
port = fetch("/api/portfolio/summary")
print(f"  Balance:    {port.get('balance', '?')}")
print(f"  Positions:  {port.get('positions_count', port.get('open_positions', '?'))}")
print(f"  Total PnL:  {port.get('total_pnl', port.get('pnl', '?'))}")

print()
print("=" * 60)
print("7. RECENT REJECTIONS")
print("=" * 60)
rej = fetch("/api/frankenstein/debug/rejections")
if rej:
    for k, v in rej.items():
        if isinstance(v, dict):
            print(f"  {k}:")
            for rk, rv in sorted(v.items(), key=lambda x: -x[1] if isinstance(x[1], (int, float)) else 0)[:10]:
                print(f"    {rk}: {rv}")
        else:
            print(f"  {k}: {v}")
else:
    print("  (no data)")

print("\n✅ Diagnosis complete")
