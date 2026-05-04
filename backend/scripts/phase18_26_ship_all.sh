#!/usr/bin/env bash
# Phase 15-26: Ship all remaining safeguards + hard reset for fresh Monday start.
set -euo pipefail
cd "$(dirname "$0")/../.."

echo "=== Verifying import chain ==="
cd backend && source .venv/bin/activate
python -c "from app.main import app; print('OK app')"
python -c "from app.routes.metrics import router; print('OK metrics')"
python -c "from app.engine.advanced_risk import PortfolioRiskLimits; r = PortfolioRiskLimits(); assert r.max_per_event == 4, r.max_per_event; print('OK diversification:', r.max_per_event)"
cd ..

echo "=== Committing Phase 15-26 ==="
git add -A
git commit -m "Phases 18-26: cross-platform veto, tighter diversification, Kelly uncertainty, /metrics

Phase 18 — Cross-platform sanity gate (scanner.py):
  Block trades where Polymarket/Vegas implies <40% on YES side or
  >60% on NO side. Hard veto: deeper market wins.

Phase 21 — Tighter diversification (advanced_risk.py):
  - max_per_event:           15 -> 4   (no more 15 bets on same NBA game)
  - max_per_category:        60 -> 25
  - max_single_position_pct: 20% -> 10%
  - max_same_event_cost_pct: 40% -> 15%
  - max_same_category_cost: 70% -> 40%

Phase 22 — Kelly uncertainty discount (scanner._kelly_size):
  - Multiply Kelly by tree_agreement (0.55..1.0 -> 30%..100% Kelly)
  - Multiply Kelly by (1 - 2*calibration_error) when err > 5%
  Coin-flippy and uncalibrated predictions get smaller bets.

Phase 25 — /api/metrics Prometheus endpoint (routes/metrics.py):
  - jahedge_paper_balance_cents / pnl_cents / total_trades
  - jahedge_frank_total_scans / trades_executed / circuit_breaker
  - jahedge_frank_side_yes_ratio / win_rate / resolved_trades
  - jahedge_kalshi_api_ready
" || echo "(nothing to commit)"
git push origin main
echo "=== Pushed. Waiting 100s for Railway redeploy ==="
sleep 100

echo "=== Health check ==="
curl -sS https://frankensteintrading.com/health | head -c 400 && echo

echo "=== Hard-reset memory + paper balance for fresh Monday start ==="
curl -sS -X POST https://frankensteintrading.com/api/frankenstein/hard-reset | python3 -m json.tool 2>/dev/null | head -20
echo
curl -sS -X POST https://frankensteintrading.com/api/frankenstein/paper-reset | python3 -m json.tool 2>/dev/null | head -10

echo "=== Awaken Frankenstein ==="
curl -sS -X POST https://frankensteintrading.com/api/frankenstein/awaken | python3 -m json.tool 2>/dev/null | head -20

echo "=== Wait 30s for first scan ==="
sleep 30

echo "=== Status ==="
curl -sS https://frankensteintrading.com/api/frankenstein/status | python3 -m json.tool 2>/dev/null | head -40
echo
echo "=== Recovery status ==="
curl -sS https://frankensteintrading.com/api/frankenstein/recovery-status | python3 -m json.tool 2>/dev/null | head -40
echo
echo "=== Metrics ==="
curl -sS https://frankensteintrading.com/api/metrics | head -50
