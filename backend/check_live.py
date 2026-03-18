#!/usr/bin/env python3
"""Quick live system diagnostic."""
import json, urllib.request

BASE = "https://api.frankensteintrading.com"

def fetch(path):
    req = urllib.request.Request(f"{BASE}{path}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

status = fetch("/api/frankenstein/status")
debug = status["last_scan_debug"]

print("=" * 60)
print("FRANKENSTEIN LIVE DIAGNOSTIC")
print("=" * 60)

print(f"\nUptime: {status['uptime_human']}")
print(f"Alive: {status['is_alive']}  Trading: {status['is_trading']}  Paused: {status['is_paused']}")

print(f"\n--- SCAN PIPELINE (last scan) ---")
print(f"  Markets scanned:     {debug['candidates']}")
print(f"  Passed model+grade:  {debug['trade_candidates']}")
print(f"  Max trades/scan:     {debug['max_trades']}")
print(f"  Portfolio rejected:  {debug['portfolio_rejections']}")
print(f"  Exec rejected:       {debug['exec_rejections']}")
print(f"  Exec SUCCESS:        {debug['exec_successes']}")

print(f"\n--- CUMULATIVE ---")
print(f"  Total scans:         {status['total_scans']}")
print(f"  Total signals:       {status['total_signals']}")
print(f"  Total executed:      {status['total_trades_executed']}")
print(f"  Total rejected:      {status['total_trades_rejected']}")

print(f"\n--- TOP CANDIDATE REJECTIONS ---")
for c in debug.get("top_candidates", [])[:10]:
    ticker = c.get("ticker", "?")
    stage = c.get("stage", "?")
    error = c.get("error", c.get("reason", ""))
    count = c.get("count", "?")
    price = c.get("price", "?")
    print(f"  {ticker}")
    print(f"    stage={stage}  count={count}  price={price}")
    if error:
        print(f"    REJECTION: {error}")

print(f"\n--- STRATEGY PARAMS ---")
sp = status["strategy"]["current_params"]
print(f"  max_spread_cents:  {sp['max_spread_cents']}")
print(f"  min_volume:        {sp['min_volume']}")
print(f"  min_confidence:    {sp['min_confidence']}")
print(f"  min_edge:          {sp['min_edge']}")
print(f"  max_position_size: {sp['max_position_size']}")

print(f"\n--- SPORTS PREDICTOR ---")
sp2 = status["sports_predictor"]
print(f"  predictions attempted: {sp2['predictions']}")
print(f"  vegas_used:            {sp2['vegas_used']}")
print(f"  ml_used:               {sp2['ml_used']}")
print(f"  kalshi_only_used:      {sp2.get('kalshi_only_used', 'NOT IN STATS')}")
print(f"  xgb_ready:             {sp2['xgb_ready']}")

print(f"\n--- MEMORY ---")
mem = status["memory"]
print(f"  total_recorded:  {mem['total_recorded']}")
print(f"  total_resolved:  {mem['total_resolved']}")
print(f"  win_rate:        {mem['win_rate']}")
print(f"  total_pnl:       {mem['total_pnl']}")

print(f"\n--- PERFORMANCE SNAPSHOT ---")
snap = status["performance"]["snapshot"]
print(f"  total_trades:     {snap['total_trades']}")
print(f"  real_trades:      {snap['real_trades']}")
print(f"  bootstrap_trades: {snap['bootstrap_trades']}")

# Check candidate filter
print(f"\n--- CANDIDATE FILTERING ---")
print(f"  Sports-only mode:  {status.get('sports_only_mode', '?')}")
print(f"  Liquidity factor:  {status.get('liquidity_factor', '?')}")
print(f"  Exchange session:  {status.get('exchange_session', '?')}")

# Odds status
try:
    sports = fetch("/api/sports/status")
    odds = sports.get("odds", {})
    print(f"\n--- ODDS API ---")
    print(f"  requests_used:      {odds.get('requests_used', '?')}")
    print(f"  requests_remaining: {odds.get('requests_remaining', '?')}")
    print(f"  component status:   {sports['components'].get('odds_client', '?')}")
except Exception as e:
    print(f"\n--- ODDS API: ERROR {e} ---")

print("\n" + "=" * 60)
print("DIAGNOSIS:")
print("=" * 60)

if debug["exec_successes"] == 0 and debug["exec_rejections"] > 0:
    reasons = [c.get("error", c.get("reason", "")) for c in debug.get("top_candidates", [])]
    unique = set(reasons)
    print(f"\n  BLOCKED: {debug['exec_rejections']} trades rejected at execution.")
    for r in unique:
        if r:
            print(f"    -> {r}")

if snap["real_trades"] == 0:
    print(f"\n  NO REAL TRADES: {snap['bootstrap_trades']} bootstrap, 0 real.")

if sp2["vegas_used"] == 0 and sp2["ml_used"] == 0:
    print(f"\n  SPORTS ENGINE: No Vegas or ML predictions used.")
    konly = sp2.get("kalshi_only_used", 0)
    if konly == 0:
        print(f"    Kalshi-only fallback also produced 0 signals.")
    else:
        print(f"    Kalshi-only fallback produced {konly} signals.")
