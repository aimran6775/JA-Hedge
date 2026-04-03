"""Phase 24 — quick status check script."""
import json
import urllib.request

def fetch(path):
    url = f"http://localhost:8000{path}"
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())

# ── Health ──
h = fetch("/health")
pt = h.get("paper_trading", {})
print("=" * 60)
print("HEALTH & PAPER TRADING")
print("=" * 60)
print(f"  Status: {h['status']}")
print(f"  Balance: ${pt.get('balance', '?')}")
print(f"  PnL: ${pt.get('pnl', '?')}")
print(f"  Total trades: {pt.get('total_trades', '?')}")
print()

# ── Frankenstein Status ──
d = fetch("/api/frankenstein/status")
print("=" * 60)
print("FRANKENSTEIN BRAIN")
print("=" * 60)
print(f"  Alive: {d.get('is_alive')}  Trading: {d.get('is_trading')}")
print(f"  Generation: {d.get('generation')}")
m = d.get("model", {})
print(f"  Model: v{m.get('version','?')}  trained={m.get('is_trained')}")
print(f"  Total scans: {d.get('total_scans')}")
print(f"  Total trades executed: {d.get('total_trades_executed')}")
print(f"  Total trades rejected: {d.get('total_trades_rejected')}")
print()

# Fill rate
fr = d.get("fill_rate_stats", {})
if fr:
    placed = fr.get("placed", 0)
    filled = fr.get("filled", 0)
    rate = filled / max(placed, 1)
    print(f"  Fill rate: {filled}/{placed} = {rate:.0%}")
    print()

# ── Category Performance ──
perf = d.get("performance", {})
retired = perf.get("retired_categories", {})
by_cat = perf.get("by_category", {})
print("=" * 60)
print("CATEGORY PERFORMANCE")
print("=" * 60)
print(f"  {'Category':15s} {'WR':>6s} {'Trades':>7s} {'PnL':>9s} {'Avg':>7s} {'Best':>7s} {'Worst':>7s}  Status")
print(f"  {'-'*15} {'-'*6} {'-'*7} {'-'*9} {'-'*7} {'-'*7} {'-'*7}  ------")
for cat, stats in sorted(by_cat.items(), key=lambda x: -x[1].get("trades", 0)):
    wr = stats.get("win_rate", 0)
    trades = stats.get("trades", 0)
    pnl = stats.get("total_pnl", 0)
    avg = stats.get("avg_pnl", 0)
    best = stats.get("best_trade", 0)
    worst = stats.get("worst_trade", 0)
    status = "RETIRED" if cat in retired else ("OK" if wr >= 0.22 else "WATCH")
    print(f"  {cat:15s} {wr:5.1%} {trades:>7d} ${pnl:>8.2f} ${avg:>6.2f} ${best:>6.2f} ${worst:>6.2f}  {status}")
print()
if retired:
    print(f"  Retired categories: {list(retired.keys())}")
else:
    print(f"  Retired categories: NONE")
print()

# ── Intelligence Sources ──
intel = fetch("/api/intelligence/status")
sources = intel.get("sources", [])
print("=" * 60)
print("INTELLIGENCE SOURCES")
print("=" * 60)
total_signals = 0
for src in sorted(sources, key=lambda x: -x.get("signal_count", 0)):
    name = src.get("name", "?")
    signals = src.get("signal_count", 0)
    fetches = src.get("fetch_count", 0)
    errors = src.get("error_count", 0)
    total_signals += signals
    icon = "OK" if signals > 0 else ("ZERO" if fetches > 0 else "OFF")
    print(f"  {icon:5s} {name:30s} signals={signals:>6d}  fetches={fetches:>5d}  errors={errors:>3d}")
print(f"\n  Total signals across all sources: {total_signals:,}")
print()

# ── Recent trades (last scan debug) ──
scan = d.get("last_scan_debug", {})
if scan:
    print("=" * 60)
    print("LAST SCAN")
    print("=" * 60)
    for k, v in scan.items():
        print(f"  {k}: {v}")
    print()

# ── Debug rejections summary ──
try:
    rej = fetch("/api/frankenstein/debug/rejections")
    total_active = rej.get("total_active", 0)
    pre_filtered = rej.get("total_pre_filtered", 0)
    candidates = rej.get("candidates", [])
    print("=" * 60)
    print("DEBUG: SCAN FUNNEL")
    print("=" * 60)
    print(f"  Active markets: {total_active}")
    print(f"  Pre-filtered: {pre_filtered}")
    print(f"  Candidates analyzed: {len(candidates)}")
    if candidates:
        tradeable = [c for c in candidates if not c.get("gates")]
        blocked = [c for c in candidates if c.get("gates")]
        print(f"  Tradeable (no gates): {len(tradeable)}")
        print(f"  Blocked (has gates): {len(blocked)}")
        if tradeable:
            print(f"\n  Top tradeable:")
            for c in tradeable[:5]:
                p = c.get("prediction", {})
                print(f"    {c['ticker'][:45]:45s} side={p.get('side')} conf={p.get('confidence',0):.2f} edge={p.get('edge',0):.4f}")
        if blocked:
            # Count gate reasons
            gate_counts = {}
            for c in blocked:
                for g in c.get("gates", []):
                    reason = g.split("=")[0].split("<")[0].split(">")[0].strip()
                    gate_counts[reason] = gate_counts.get(reason, 0) + 1
            print(f"\n  Gate blockers:")
            for reason, count in sorted(gate_counts.items(), key=lambda x: -x[1]):
                print(f"    {reason}: {count}")
except Exception as e:
    print(f"  Debug rejections: {e}")

print()
print("=" * 60)
print("SUMMARY")
print("=" * 60)
balance = float(pt.get("balance", 10000))
pnl_val = float(pt.get("pnl", 0))
total_t = pt.get("total_trades", 0)
print(f"  Paper balance: ${balance:,.2f}  (PnL: ${pnl_val:+.2f})")
print(f"  Total trades: {total_t}")
print(f"  Intelligence: {total_signals:,} signals from {sum(1 for s in sources if s.get('signal_count',0) > 0)}/{len(sources)} sources")
if retired:
    print(f"  WARNING: {len(retired)} categories retired: {list(retired.keys())}")
print("=" * 60)
