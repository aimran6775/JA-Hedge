#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/../.."

echo "=== Verifying import chain ==="
cd backend && ~/.jahedge-venv/bin/python -c "from app.main import app; print('OK')" && cd ..

echo "=== Committing and pushing ==="
git add -A
git commit -m "Phase 22b: fix circuit breaker BREAKEVEN bug

Circuit breaker was counting BREAKEVEN (sell/exit) trades as failures.
Since breakeven trades are sell/exit records (not prediction failures),
they were making accuracy = 0 wins / (0+0+N breakevens) = 0%, tripping
the breaker within 18 minutes of every restart.

Fix: only count WIN and LOSS trades in accuracy calculation."

git push origin main
echo "=== Pushed. Railway will auto-deploy. ==="
