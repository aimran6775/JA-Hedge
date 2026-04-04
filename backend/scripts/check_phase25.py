#!/usr/bin/env python3
"""Check Phase 25 deployment status and diagnose issues."""
import json
import urllib.request

BASE = "https://frankensteintrading.com"

def fetch(path):
    with urllib.request.urlopen(f"{BASE}{path}", timeout=15) as r:
        return json.loads(r.read())

def main():
    # 1. Status
    st = fetch("/api/frankenstein/status")
    print("=" * 60)
    print("FRANKENSTEIN STATUS")
    print("=" * 60)
    print(f"  Version:       {st['version']}")
    print(f"  Alive:         {st['is_alive']}")
    print(f"  Trading:       {st['is_trading']}")
    print(f"  Paused:        {st['is_paused']}")
    print(f"  Learning mode: {st['learning_mode']}")
    print(f"  Learning prog: {st['learning_progress']}")
    print(f"  Real trades:   {st['real_trades']}")
    print(f"  Uptime:        {st['uptime_human']}")
    print(f"  Daily trades:  {st['daily_trades']}/{st['daily_trade_cap']}")
    print(f"  Total scans:   {st['total_scans']}")
    print(f"  Trades exec:   {st['total_trades_executed']}")
    print(f"  Trades reject: {st['total_trades_rejected']}")
    print(f"  Last scan:     {st['last_scan_ms']}ms")
    print(f"  Scan debug:    {st['last_scan_debug']}")
    print(f"  Exchange:      {st['exchange_session']}")
    print(f"  Liquidity:     {st['liquidity_factor']}")
    
    # Learner
    lr = st.get('learner', {})
    print(f"\n  LEARNER:")
    print(f"    Generation:       {lr.get('generation')}")
    print(f"    Version:          {lr.get('current_version')}")
    print(f"    Champion:         {lr.get('champion')}")
    print(f"    Champion AUC:     {lr.get('champion_auc')}")
    print(f"    Champion samples: {lr.get('champion_samples')}")
    print(f"    Total retrains:   {lr.get('total_retrains')}")
    print(f"    Last train count: {lr.get('last_train_count')}")
    print(f"    Needs retrain:    {lr.get('needs_retrain')}")
    
    # Strategy
    sp = st.get('strategy', {}).get('current_params', {})
    print(f"\n  STRATEGY:")
    print(f"    min_confidence:  {sp.get('min_confidence')}")
    print(f"    min_edge:        {sp.get('min_edge')}")
    print(f"    scan_interval:   {sp.get('scan_interval')}")
    print(f"    max_positions:   {sp.get('max_simultaneous_positions')}")
    
    # Memory
    mem = st.get('memory', {})
    print(f"\n  MEMORY:")
    print(f"    Total recorded:  {mem.get('total_recorded')}")
    print(f"    Resolved:        {mem.get('total_resolved')}")
    print(f"    Pending:         {mem.get('pending')}")
    print(f"    Outcomes:        {mem.get('outcomes')}")
    
    # WS Bridge
    ws = st.get('ws_bridge', {})
    print(f"\n  WS BRIDGE:")
    print(f"    Connected:       {ws.get('connected')}")
    print(f"    Reconnects:      {ws.get('ws_stats', {}).get('reconnect_attempts')}")
    print(f"    Ticker updates:  {ws.get('ticker_updates')}")
    
    # 2. Rejections
    print("\n" + "=" * 60)
    print("REJECTION ANALYSIS")
    print("=" * 60)
    rej = fetch("/api/frankenstein/debug/rejections")
    print(f"  Total active markets:  {rej['total_active']}")
    print(f"  Pre-filtered:          {rej['total_pre_filtered']}")
    print(f"  Model trained (rej):   {rej['model_trained']}")
    print(f"  Learning mode (rej):   {rej['is_learning_mode']}")
    
    candidates = rej.get('candidates', [])
    would_exec = [c for c in candidates if c.get('would_execute')]
    blocked = [c for c in candidates if c.get('gates_blocking')]
    
    print(f"\n  Total candidates:       {len(candidates)}")
    print(f"  Would execute:          {len(would_exec)}")
    print(f"  Blocked by gates:       {len(blocked)}")
    
    # Edge distribution
    edges = [c['prediction']['edge'] for c in candidates]
    neg_edges = [e for e in edges if e < 0]
    pos_edges = [e for e in edges if e > 0]
    print(f"\n  EDGE DISTRIBUTION:")
    print(f"    Positive edges:  {len(pos_edges)}")
    print(f"    Negative edges:  {len(neg_edges)}")
    if edges:
        print(f"    Min edge:        {min(edges):.4f}")
        print(f"    Max edge:        {max(edges):.4f}")
        print(f"    Mean edge:       {sum(edges)/len(edges):.4f}")
    
    # Show some would-execute candidates
    if would_exec:
        print(f"\n  WOULD-EXECUTE CANDIDATES (top 10):")
        for c in would_exec[:10]:
            p = c['prediction']
            m = c['market']
            g = c['confidence_grade']
            print(f"    {c['ticker'][:45]}")
            print(f"      side={p['side']} conf={p['confidence']:.2f} edge={p['edge']:+.4f} prob={p['prob']:.3f}")
            print(f"      mid={m['midpoint']:.3f} spread={m['spread']:.2f} vol={m['volume']} grade={g['grade']}")
    
    # Show blocking gates
    if blocked:
        print(f"\n  BLOCKED CANDIDATES (top 10):")
        gate_counts = {}
        for c in blocked:
            for g in c['gates_blocking']:
                gate_counts[g] = gate_counts.get(g, 0) + 1
        print(f"    Gate counts: {gate_counts}")
        for c in blocked[:5]:
            print(f"    {c['ticker'][:45]}: {c['gates_blocking']}")
    
    # 3. Check if scan is finding candidates but not executing
    print("\n" + "=" * 60)
    print("DIAGNOSIS")
    print("=" * 60)
    
    scan_debug = st.get('last_scan_debug', {})
    exit_reason = scan_debug.get('exit', 'unknown')
    print(f"  Scan exit reason: {exit_reason}")
    
    if exit_reason == 'all_failed_feature_gate':
        print("  ⚠️  ALL candidates failed the feature gate!")
        print("  This means features are computed but fail quality checks.")
        print("  Possible causes:")
        print("    - model.is_trained returning True incorrectly")
        print("    - Feature gate threshold too strict")
        print("    - All edges negative (wrong sign)")
    
    if rej['model_trained'] and not rej['is_learning_mode'] and st['learning_mode']:
        print("  ⚠️  INCONSISTENCY: status says learning_mode=True but rejections says False!")
        print("  This means the rejections endpoint is computing model_trained differently")
    
    if all(e < 0 for e in edges):
        print("  ⚠️  ALL EDGES ARE NEGATIVE! Edge calculation might be inverted.")
    
    # Check what model_trained means
    print(f"\n  Model state:")
    print(f"    learner.champion: {lr.get('champion')}")
    print(f"    learner.champion_auc: {lr.get('champion_auc')}")
    print(f"    learner.champion_samples: {lr.get('champion_samples')}")
    print(f"    learner.total_retrains: {lr.get('total_retrains')}")
    
    # 4. Portfolio
    print("\n" + "=" * 60)
    print("PORTFOLIO")
    print("=" * 60)
    try:
        pf = fetch("/api/portfolio/balance")
        print(f"  Balance: {pf}")
    except Exception as e:
        print(f"  Error: {e}")

if __name__ == "__main__":
    main()
