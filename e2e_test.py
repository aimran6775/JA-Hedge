#!/usr/bin/env python3
"""JA Hedge — Full End-to-End Test Script."""

import json
import sys
import time
import urllib.request
import urllib.error

BASE = "https://backend-production-0a8a.up.railway.app"
FRONTEND = "https://frontend-production-2c6d.up.railway.app"

results = {"passed": 0, "failed": 0, "errors": []}


def test(name, url, method="GET", body=None, check=None):
    """Run a single test."""
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode() if body else None,
            headers={"Content-Type": "application/json"} if body else {},
            method=method,
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode())
            if check:
                ok, detail = check(data)
            else:
                ok, detail = True, "200 OK"
            status = "✅" if ok else "❌"
            if ok:
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(f"{name}: {detail}")
            print(f"  {status} {name:45s} {detail}")
            return data
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"{name}: {e}")
        print(f"  ❌ {name:45s} ERROR: {e}")
        return None


def test_page(name, url):
    """Test that a frontend page returns 200."""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            ok = resp.status == 200
            status = "✅" if ok else "❌"
            if ok:
                results["passed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(f"{name}: HTTP {resp.status}")
            print(f"  {status} {name:45s} HTTP {resp.status}")
    except Exception as e:
        results["failed"] += 1
        results["errors"].append(f"{name}: {e}")
        print(f"  ❌ {name:45s} ERROR: {e}")


print("=" * 60)
print("  JA HEDGE — FULL END-TO-END TEST")
print(f"  {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 60)

# ── 1. HEALTH & AUTH ─────────────────────────────────────────
print("\n🏥 HEALTH & AUTH")
test("Health check", f"{BASE}/health",
     check=lambda d: (d.get("status") == "ok", f"status={d.get('status')}, components={len(d.get('components', {}))}"))
test("Auth check", f"{BASE}/health/auth",
     check=lambda d: (d.get("api_initialized") is True, f"api_init={d.get('api_initialized')}, key={d.get('key_id_prefix')}"))
test("Root endpoint", f"{BASE}/",
     check=lambda d: (d.get("name") == "JA Hedge", f"name={d.get('name')}, brain={d.get('brain')}"))

# ── 2. MARKETS ────────────────────────────────────────────────
print("\n📊 MARKETS")
mdata = test("Markets list", f"{BASE}/api/markets?limit=5",
     check=lambda d: (d.get("total", 0) > 0, f"total={d.get('total')}, source={d.get('source')}"))
test("Markets search (bitcoin)", f"{BASE}/api/markets?search=bitcoin&limit=3",
     check=lambda d: (d.get("total", 0) > 0, f"found={d.get('total')} bitcoin markets"))
test("Markets search (NBA)", f"{BASE}/api/markets?search=NBA&limit=3",
     check=lambda d: (d.get("total", 0) > 0, f"found={d.get('total')} NBA markets"))

# Get a tradeable ticker
tradeable_ticker = None
if mdata:
    for m in mdata.get("markets", []):
        sp = m.get("spread")
        if sp is not None and sp <= 0.20:
            tradeable_ticker = m["ticker"]
            break

# ── 3. PORTFOLIO ──────────────────────────────────────────────
print("\n💰 PORTFOLIO")
test("Balance", f"{BASE}/api/portfolio/balance",
     check=lambda d: (d.get("balance_cents", 0) > 0, f"${d.get('balance_dollars')} ({d.get('position_count')} positions)"))
test("Positions", f"{BASE}/api/portfolio/positions",
     check=lambda d: (isinstance(d, list), f"{len(d)} open positions"))
test("PnL", f"{BASE}/api/portfolio/pnl",
     check=lambda d: ("daily_pnl" in d, f"daily_pnl={d.get('daily_pnl')}, trades={d.get('daily_trades')}"))
test("Fills", f"{BASE}/api/portfolio/fills?limit=10",
     check=lambda d: (isinstance(d, list), f"{len(d)} recent fills"))

# ── 4. ORDERS (manual trade) ─────────────────────────────────
print("\n📝 ORDERS")
# Find best ticker for test trade
test_ticker = "KXNBASPREAD-26MAR14MILATL-ATL26"
order_data = test("Place order (paper)", f"{BASE}/api/orders", method="POST",
     body={"ticker": test_ticker, "side": "yes", "action": "buy", "count": 1, "price_cents": 9},
     check=lambda d: (d.get("success") is True, f"order_id={d.get('order_id')}, latency={d.get('latency_ms', 0):.1f}ms"))

# Verify balance changed
test("Balance after trade", f"{BASE}/api/portfolio/balance",
     check=lambda d: (d.get("position_count", 0) >= 1, f"${d.get('balance_dollars')} ({d.get('position_count')} positions)"))

# ── 5. RISK MANAGEMENT ───────────────────────────────────────
print("\n🛡️  RISK MANAGEMENT")
test("Risk snapshot", f"{BASE}/api/risk/snapshot",
     check=lambda d: ("kill_switch_active" in d, f"exposure={d.get('total_exposure')}, kill={d.get('kill_switch_active')}"))

# Test kill switch
test("Kill switch ON", f"{BASE}/api/risk/kill-switch?activate=true", method="POST",
     check=lambda d: (d.get("kill_switch_active") is True, "activated"))

# Try order with kill switch on (should fail)
test("Order blocked by kill switch", f"{BASE}/api/orders", method="POST",
     body={"ticker": test_ticker, "side": "yes", "action": "buy", "count": 1, "price_cents": 9},
     check=lambda d: (d.get("success") is False, f"blocked correctly"))

# Deactivate
test("Kill switch OFF", f"{BASE}/api/risk/kill-switch?activate=false", method="POST",
     check=lambda d: (d.get("kill_switch_active") is False, "deactivated"))

# ── 6. STRATEGY ENGINE ───────────────────────────────────────
print("\n📈 STRATEGY ENGINE")
test("Strategy status", f"{BASE}/api/strategies/status",
     check=lambda d: (d.get("total_strategies") == 8, f"{d.get('enabled_strategies')}/{d.get('total_strategies')} enabled, {d.get('total_signals_generated')} signals"))
test("Strategy signals", f"{BASE}/api/strategies/signals?n=5",
     check=lambda d: ("signals" in d, f"{d.get('total_signals')} signals returned"))
test("Toggle strategy ON", f"{BASE}/api/strategies/toggle", method="POST",
     body={"strategy": "kelly_optimal", "enabled": True},
     check=lambda d: (d.get("enabled") is True, "kelly_optimal enabled"))
test("Toggle strategy OFF", f"{BASE}/api/strategies/toggle", method="POST",
     body={"strategy": "kelly_optimal", "enabled": False},
     check=lambda d: (d.get("enabled") is False, "kelly_optimal disabled"))
test("Update config", f"{BASE}/api/strategies/config", method="POST",
     body={"strategy": "momentum_chaser", "min_confidence": 0.58},
     check=lambda d: (d.get("status") == "ok", f"config updated"))

# Manual scan (the big test)
scan_data = test("Manual scan (500 markets)", f"{BASE}/api/strategies/scan", method="POST",
     check=lambda d: (d.get("markets_scanned", 0) > 0, f"scanned={d.get('markets_scanned')}, signals={d.get('total_signals')}"))

# ── 7. AI STRATEGY (legacy) ──────────────────────────────────
print("\n🤖 AI STRATEGY (legacy)")
test("Strategy status", f"{BASE}/api/strategy/status",
     check=lambda d: ("running" in d or "strategy_id" in d, f"running={d.get('running')}"))

# ── 8. FRANKENSTEIN BRAIN ─────────────────────────────────────
print("\n🧟 FRANKENSTEIN BRAIN")
frank_data = test("Frankenstein status", f"{BASE}/api/frankenstein/status",
     check=lambda d: ("is_alive" in d or "state" in d, f"alive={d.get('is_alive', d.get('state', {}).get('is_alive'))}, scans={d.get('total_scans', d.get('state', {}).get('total_scans'))}"))
test("Frankenstein health", f"{BASE}/api/frankenstein/health",
     check=lambda d: ("alive" in d or "health" in d or "status" in d, f"alive={d.get('alive')}, trading={d.get('trading')}"))

# Chat
test("Chat welcome", f"{BASE}/api/frankenstein/chat/welcome",
     check=lambda d: (True, f"keys: {list(d.keys())[:3]}"))
test("Chat message", f"{BASE}/api/frankenstein/chat", method="POST",
     body={"message": "What is your current strategy?"},
     check=lambda d: ("content" in d or "response" in d or "message" in d or "reply" in d, f"response received"))
test("Chat history", f"{BASE}/api/frankenstein/chat/history?n=5",
     check=lambda d: (isinstance(d, list), f"{len(d)} messages"))

# ── 9. SPORTS MODULE ─────────────────────────────────────────
print("\n🏀 SPORTS MODULE")
test("Sports status", f"{BASE}/api/sports/status",
     check=lambda d: (True, f"keys: {list(d.keys())[:4]}"))
test("Sports markets", f"{BASE}/api/sports/markets",
     check=lambda d: ("total_sports_markets" in d, f"sports={d.get('total_sports_markets')}, total={d.get('total_all_markets')}"))
test("Sports odds", f"{BASE}/api/sports/odds",
     check=lambda d: ("total_games" in d, f"games={d.get('total_games')}"))
test("Sports live", f"{BASE}/api/sports/live",
     check=lambda d: ("live_games" in d, f"live={d.get('live_games')}"))
test("Sports signals", f"{BASE}/api/sports/signals",
     check=lambda d: ("pending_signals" in d, f"pending={d.get('pending_signals')}"))
test("Sports performance", f"{BASE}/api/sports/performance",
     check=lambda d: (True, f"keys: {list(d.keys())[:4]}"))

# ── 10. AGENT (legacy) ───────────────────────────────────────
print("\n🕵️  AGENT (legacy)")
test("Agent status", f"{BASE}/api/agent/status",
     check=lambda d: ("status" in d, f"status={d.get('status')}"))

# ── 11. ALERTS ────────────────────────────────────────────────
print("\n🔔 ALERTS")
test("Alerts list", f"{BASE}/api/alerts",
     check=lambda d: (isinstance(d, (list, dict)), "alerts endpoint working"))

# ── 12. DASHBOARD ─────────────────────────────────────────────
print("\n📋 DASHBOARD")
test("Dashboard overview", f"{BASE}/api/dashboard",
     check=lambda d: (True, f"keys: {list(d.keys())[:5]}"))

# ── 13. FRONTEND PAGES ───────────────────────────────────────
print("\n🌐 FRONTEND PAGES")
pages = [
    ("Home", f"{FRONTEND}/"),
    ("Dashboard", f"{FRONTEND}/dashboard"),
    ("Frankenstein", f"{FRONTEND}/dashboard/frankenstein"),
    ("Strategies", f"{FRONTEND}/dashboard/strategies"),
    ("Sports", f"{FRONTEND}/dashboard/sports"),
    ("Markets", f"{FRONTEND}/dashboard/markets"),
    ("Trading", f"{FRONTEND}/dashboard/trading"),
    ("Portfolio", f"{FRONTEND}/dashboard/portfolio"),
    ("AI Agent", f"{FRONTEND}/dashboard/agent"),
    ("AI Engine", f"{FRONTEND}/dashboard/ai"),
    ("Risk", f"{FRONTEND}/dashboard/risk"),
    ("Settings", f"{FRONTEND}/dashboard/settings"),
]
for name, url in pages:
    test_page(f"Page: {name}", url)

# ── 14. FULL TRADING PIPELINE TEST ───────────────────────────
print("\n⚡ FULL TRADING PIPELINE (place → verify → sell → verify)")

# Use a DIFFERENT market for the pipeline test to avoid position limit conflicts
# (earlier tests may have accumulated positions on test_ticker)
pipeline_ticker = "KXNBASPREAD-26MAR14MILATL-ATL20"  # different spread line

# Place a buy order
buy_result = test("Buy 2 YES contracts", f"{BASE}/api/orders", method="POST",
     body={"ticker": pipeline_ticker, "side": "yes", "action": "buy", "count": 2, "price_cents": 17},
     check=lambda d: (d.get("success") is True, f"order={d.get('order_id')}, err={d.get('error')}"))

# Check position
test("Position appeared", f"{BASE}/api/portfolio/positions",
     check=lambda d: (len(d) > 0, f"{len(d)} positions"))

# Check fills
test("Fills recorded", f"{BASE}/api/portfolio/fills?limit=10",
     check=lambda d: (len(d) > 0, f"{len(d)} fills"))

# Sell to close
sell_result = test("Sell 1 YES (partial close)", f"{BASE}/api/orders", method="POST",
     body={"ticker": pipeline_ticker, "side": "yes", "action": "sell", "count": 1, "price_cents": 20},
     check=lambda d: (d.get("success") is True, f"order={d.get('order_id')}"))

# Final balance
test("Final balance check", f"{BASE}/api/portfolio/balance",
     check=lambda d: (True, f"${d.get('balance_dollars')} | {d.get('position_count')} pos | {d.get('open_orders')} orders"))

# Final PnL
test("Final PnL check", f"{BASE}/api/portfolio/pnl",
     check=lambda d: (True, f"pnl=${d.get('daily_pnl'):.2f} | {d.get('daily_trades')} trades | fees=${d.get('daily_fees'):.2f}"))

# ── SUMMARY ───────────────────────────────────────────────────
print("\n" + "=" * 60)
total = results["passed"] + results["failed"]
pct = results["passed"] / total * 100 if total > 0 else 0
print(f"  RESULTS: {results['passed']}/{total} passed ({pct:.0f}%)")
print(f"  ✅ Passed: {results['passed']}")
print(f"  ❌ Failed: {results['failed']}")
if results["errors"]:
    print(f"\n  FAILURES:")
    for e in results["errors"]:
        print(f"    • {e}")
print("=" * 60)

sys.exit(0 if results["failed"] == 0 else 1)
