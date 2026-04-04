#!/usr/bin/env bash
# Deploy autonomous trading fixes:
# 1. Auto-detect production mode when API keys present
# 2. Maker-mode-aware market filters (no volume/spread requirement)
# 3. Widened strategy params for maker mode
# 4. Health endpoint shows effective_mode + rest_url
set -e
cd "$(dirname "$0")/../.."

echo "=== Verifying import chain ==="
cd backend && python -c "from app.main import app; print('Import OK')" && cd ..

echo ""
echo "=== Committing & pushing ==="
git add -A
git commit -m "fix: auto-upgrade to production mode + maker-aware market filters

Root cause: JAHEDGE_MODE defaulted to demo, hitting Kalshi sandbox
with empty order books → 98% of 10K markets had zero prices →
scanner rejected everything → zero trades ever.

Fixes:
- config.py: effective_mode auto-upgrades to production when API keys exist
- scanner.py: maker mode skips volume/spread/bid-ask checks (we CREATE liquidity)
- strategy.py: max_spread_cents 15→40, min_volume 15→0
- main.py: health endpoint shows effective_mode + rest_url for debugging
- Cents-based price fallback for markets missing dollar-based fields"

git push origin main

echo ""
echo "=== Deployed. Waiting 90s for Railway build ==="
sleep 90

echo ""
echo "=== Checking health ==="
curl -s https://frankensteintrading.com/health | python3 -m json.tool

echo ""
echo "=== Checking Frankenstein status ==="
curl -s https://frankensteintrading.com/api/frankenstein/status | python3 -m json.tool | head -40
