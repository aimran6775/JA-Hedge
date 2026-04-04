#!/usr/bin/env python3
"""Deep analysis of live Frankenstein trading."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())

print("=" * 70)
print("DEEP ANALYSIS — FRANKENSTEIN LIVE")
print("=" * 70)

# 1. Status
st = fetch("/api/frankenstein/status")
print(f"\n📊 OVERVIEW")
print(f"  Uptime:          {st['uptime_human']}")
print(f"  Daily trades:    {st['daily_trades']}/{st['daily_trade_cap']}")
print(f"  Total scans:     {st['total_scans']}")
print(f"  Learning mode:   {st['learning_mode']}")
print(f"  Learning prog:   {st['learning_progress']}")
print(f"  Real trades:     {st['real_trades']}")
print(f"  Exchange:        {st['exchange_session']}")

# Memory analysis
mem = st.get('memory', {})
outcomes = mem.get('outcomes', {})
print(f"\n📦 MEMORY")
print(f"  Total recorded:  {mem.get('total_recorded')}")
print(f"  Resolved:        {mem.get('total_resolved')}")
print(f"  Pending:         {outcomes.get('pending', 0)}")
print(f"  Win:             {outcomes.get('win', 0)}")
print(f"  Loss:            {outcomes.get('loss', 0)}")
print(f"  Breakeven:       {outcomes.get('breakeven', 0)}")
print(f"  Expired:         {outcomes.get('expired', 0)}")
print(f"  Unique tickers:  {mem.get('unique_tickers')}")
total_resolved = outcomes.get('win',0) + outcomes.get('loss',0) + outcomes.get('breakeven',0) + outcomes.get('expired',0)
usable_labels = outcomes.get('win',0) + outcomes.get('loss',0)
print(f"  Usable labels:   {usable_labels} (win+loss with definitive market_result)")

# Category breakdown
cat_analytics = mem.get('category_analytics', {})
if cat_analytics:
    print(f"\n📁 CATEGORY BREAKDOWN")
    for cat, stats in cat_analytics.items():
        print(f"  {cat}: {stats.get('trades',0)} trades, WR={stats.get('win_rate',0):.1%}, PnL=${stats.get('total_pnl',0)/100:.2f}")

# Performance
perf = st.get('performance', {})
snap = perf.get('snapshot', {})
print(f"\n📈 PERFORMANCE")
print(f"  Total PnL:       ${snap.get('total_pnl', 0)/100:.2f}")
print(f"  Daily PnL:       ${snap.get('daily_pnl', 0)/100:.2f}")
print(f"  Win rate:        {snap.get('win_rate', 0):.1%}")
print(f"  Trades today:    {snap.get('trades_today', 0)}")
print(f"  Consec losses:   {snap.get('consecutive_losses', 0)}")
print(f"  Max drawdown:    {snap.get('max_drawdown', 0):.1%}")
print(f"  Regime:          {snap.get('regime', 'unknown')}")
print(f"  Should pause:    {perf.get('should_pause', False)}")
print(f"  Pause reason:    {perf.get('pause_reason', 'ok')}")

# Strategy adaptation
strat = st.get('strategy', {})
sp = strat.get('current_params', {})
print(f"\n⚙️ STRATEGY (adapted)")
print(f"  min_confidence:  {sp.get('min_confidence', 0):.4f}")
print(f"  min_edge:        {sp.get('min_edge', 0):.4f}")
print(f"  scan_interval:   {sp.get('scan_interval', 0):.1f}s")
print(f"  aggression:      {strat.get('aggression', 0)}")
print(f"  adaptations:     {strat.get('total_adaptations', 0)}")

# Capital
cap = st.get('capital', {})
print(f"\n💰 CAPITAL")
print(f"  Balance:         ${cap.get('balance_cents', 0)/100:.2f}")
print(f"  Reserved:        ${cap.get('reserved_cents', 0)/100:.2f}")
print(f"  Available:       ${cap.get('available_cents', 0)/100:.2f}")
print(f"  Reserved %:      {cap.get('reserved_pct', '0%')}")
print(f"  Orders approved: {cap.get('orders_approved', 0)}")
print(f"  Orders gated:    {cap.get('orders_gated', 0)}")

# Portfolio risk
risk = st.get('portfolio_risk', {})
print(f"\n🛡️ PORTFOLIO RISK")
print(f"  Positions:       {risk.get('total_positions', 0)}")
print(f"  Deployed:        {risk.get('total_deployed', '$0.00')}")
print(f"  Max loss:        {risk.get('max_loss', '$0.00')}")
print(f"  Max gain:        {risk.get('max_gain', '$0.00')}")

# Learner
lr = st.get('learner', {})
print(f"\n🧠 LEARNER")
print(f"  Generation:      {lr.get('generation')}")
print(f"  Version:         {lr.get('current_version')}")
print(f"  Total retrains:  {lr.get('total_retrains')}")
print(f"  Needs retrain:   {lr.get('needs_retrain')}")
print(f"  Champion AUC:    {lr.get('champion_auc')}")
print(f"  Champion samples:{lr.get('champion_samples')}")

# Sports
sp_det = st.get('sports_detector', {})
sp_pred = st.get('sports_predictor', {})
print(f"\n⚾ SPORTS")
print(f"  Detections:      {sp_det.get('cached_detections', 0)}")
print(f"  Sports found:    {sp_det.get('sports_detected', 0)}")
print(f"  By sport:        {sp_det.get('by_sport', {})}")
print(f"  Predictions:     {sp_pred.get('predictions', 0)}")

# WS Bridge
ws = st.get('ws_bridge', {})
print(f"\n🔌 WS BRIDGE")
print(f"  Connected:       {ws.get('connected')}")
print(f"  Reconnects:      {ws.get('ws_stats', {}).get('reconnect_attempts', 0)}")
print(f"  Ticker updates:  {ws.get('ticker_updates', 0)}")

# Order Manager
om = st.get('order_manager', {})
fr = om.get('fill_rate_stats', {})
print(f"\n📋 ORDER MANAGER")
print(f"  Placed:          {fr.get('placed', 0)}")
print(f"  Filled:          {fr.get('filled', 0)}")
print(f"  Cancelled:       {fr.get('cancelled', 0)}")
print(f"  Fill rate:       {om.get('fill_rate', 0):.1%}")

# Portfolio balance
print(f"\n💵 PORTFOLIO BALANCE")
try:
    pf = fetch("/api/portfolio/balance")
    print(f"  Balance:         ${pf.get('balance_dollars', '?')}")
    print(f"  Exposure:        ${pf.get('total_exposure', 0)/100:.2f}" if isinstance(pf.get('total_exposure'), (int,float)) else f"  Exposure:        {pf.get('total_exposure', '?')}")
    print(f"  Positions:       {pf.get('position_count', 0)}")
    print(f"  Open orders:     {pf.get('open_orders', 0)}")
except Exception as e:
    print(f"  Error: {e}")

# Trades/fills
print(f"\n📜 RECENT TRADES")
try:
    trades = fetch("/api/frankenstein/trades?limit=20")
    if isinstance(trades, list):
        for t in trades[:10]:
            ticker = t.get('ticker', '?')[:40]
            side = t.get('side', '?')
            outcome = t.get('outcome', '?')
            pnl = t.get('pnl_cents', 0)
            ts = t.get('timestamp', 0)
            conf = t.get('confidence', 0)
            edge = t.get('edge', 0)
            print(f"  {ticker:40s} {side:3s} out={outcome:10s} pnl={pnl:+4d}¢ conf={conf:.2f} edge={edge:+.4f}")
    elif isinstance(trades, dict):
        trade_list = trades.get('trades', trades.get('recent', []))
        for t in trade_list[:10]:
            ticker = t.get('ticker', '?')[:40]
            side = t.get('side', '?')
            outcome = t.get('outcome', '?')
            pnl = t.get('pnl_cents', 0)
            conf = t.get('confidence', 0)
            edge = t.get('edge', 0)
            print(f"  {ticker:40s} {side:3s} out={outcome:10s} pnl={pnl:+4d}¢ conf={conf:.2f} edge={edge:+.4f}")
except Exception as e:
    print(f"  Error fetching trades: {e}")

# Key diagnostic
print(f"\n" + "=" * 70)
print(f"🔍 DIAGNOSIS")
print(f"=" * 70)

pending = outcomes.get('pending', 0)
breakeven = outcomes.get('breakeven', 0)
total_trades = st.get('daily_trades', 0)

if pending > 200:
    print(f"  ⚠️  HIGH PENDING ({pending}): Many positions open, waiting for settlement")
    print(f"     This is EXPECTED in learning mode with hold-to-settlement strategy.")
    print(f"     Positions will resolve when markets settle (usually within 24h).")

if breakeven > 0 and usable_labels == 0:
    print(f"  ⚠️  ALL RESOLVED AS BREAKEVEN ({breakeven}): These are from the old churn phase.")
    print(f"     The new positions ({pending} pending) should resolve with real labels.")

if total_trades >= 280:
    print(f"  ⚠️  NEAR DAILY CAP ({total_trades}/300): System is actively trading.")
    print(f"     May need to increase MAX_DAILY_TRADES if positions resolve well.")

# Training readiness
print(f"\n🎓 TRAINING READINESS")
print(f"  Usable labels (win+loss):  {usable_labels}")
print(f"  Need for first training:   50")
print(f"  Pending that will resolve: {pending}")
if usable_labels >= 50:
    print(f"  ✅ READY TO TRAIN! Learner should auto-retrain soon.")
elif pending >= 50:
    pct = usable_labels / 50 * 100
    print(f"  🔄 {pct:.0f}% ready. {pending} pending positions will provide labels once markets settle.")
    print(f"     Sports markets typically settle within hours of game end.")
else:
    print(f"  ❌ Need more trades. Only {usable_labels + pending} total (need 50+ resolved).")
