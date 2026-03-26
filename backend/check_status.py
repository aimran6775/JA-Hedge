#!/usr/bin/env python3
import subprocess, json

r = subprocess.run(["curl", "-s", "https://api.frankensteintrading.com/api/frankenstein/status"], capture_output=True, text=True)
d = json.loads(r.stdout)

print("=== CORE STATUS ===")
print(f"  Alive: {d['is_alive']}  |  Trading: {d['is_trading']}  |  Paused: {d['is_paused']}")
print(f"  Version: {d['version']}  |  Gen: {d['generation']}")
print(f"  Scans: {d['total_scans']}  |  Signals: {d['total_signals']}  |  Trades: {d['total_trades_executed']}")
print(f"  Last scan: {d['last_scan_ms']}ms")

m = d["memory"]
print(f"\n=== MEMORY ===")
print(f"  Recorded: {m['total_recorded']}  |  Resolved: {m['total_resolved']}  |  Pending: {m['pending']}")
print(f"  Win rate: {m['win_rate']}  |  PnL: {m['total_pnl']}  |  Avg: {m['avg_pnl_per_trade']}")
print(f"  Outcomes: W={m['outcomes']['win']} L={m['outcomes']['loss']} BE={m['outcomes']['breakeven']}")

l = d["learner"]
print(f"\n=== LEARNER ===")
print(f"  Gen: {l['generation']}  |  AUC: {l['champion_auc']:.4f}  |  Samples: {l['champion_samples']}")
print(f"  Retrains: {l['total_retrains']}  |  Promotions: {l['total_promotions']}")
print(f"  Top features: {list(l['top_features'].keys())[:5]}")

h = d["health"]
print(f"\n=== HEALTH ===")
print(f"  Healthy: {h['healthy']}  |  Errors: {h['total_errors']}")
for comp, info in h["components"].items():
    icon = "Y" if info["healthy"] else "N"
    print(f"    {comp}: [{icon}] {info['details']}")

p = d["portfolio_risk"]
print(f"\n=== PORTFOLIO ===")
print(f"  Positions: {p['total_positions']}  |  Deployed: {p['total_deployed']}")
print(f"  Max loss: {p['max_loss']}  |  Max gain: {p['max_gain']}")

sd = d.get("last_scan_debug", {})
print(f"\n=== LAST SCAN ===")
print(f"  Candidates: {sd.get('candidates',0)}  |  Trade candidates: {sd.get('trade_candidates',0)}")
print(f"  Signals: {sd.get('signals',0)}  |  Open positions: {sd.get('open_positions',0)}")

s = d.get("strategy", {}).get("current_params", {})
print(f"\n=== STRATEGY PARAMS ===")
print(f"  Min confidence: {s.get('min_confidence',0):.3f}  |  Min edge: {s.get('min_edge',0):.3f}")
print(f"  Kelly fraction: {s.get('kelly_fraction',0):.3f}  |  Max position: {s.get('max_position_size',0)}")
print(f"  Aggression: {d.get('strategy',{}).get('aggression','?')}")
