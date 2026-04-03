#!/bin/bash
set -e
cd "$(dirname "$0")"

git add -A
git commit -m "fix: Phase 22 — 5 accuracy root causes

Root cause analysis from 1,192 trades (31.1% WR, -\$157.72 PnL):

1. Toxic market blacklist: blocked KXEPLGOAL (2% WR), KXEPLFIRSTGOAL (5%),
   KXMVECROSSCATEGORY (5%), KXNCAAMB1HSPREAD (13%), KXQUICKSETTLE (34%),
   and 15-min crypto (unpredictable coin flips). Both full scan and reactive.

2. Edge floor raised: learning-mode min edge 0.03->0.06. Absolute floor of
   0.04 for ALL trades. Data: 443 trades at edge~0 had 22% WR (coin flips),
   62 trades at edge>=0.05 had 95% WR.

3. Faster outcome resolution: extreme price threshold 0.99/0.01->0.95/0.05.
   Timeout reduced 48h->6h with price-based resolution (was: 45.6% expired).

4. Circuit breaker tuning: min trades 30->15 (faster trip), cooldown 4h->2h
   (faster recovery).

5. Diagnosis tooling: diagnose_accuracy.py for ongoing monitoring."

echo "Committed"
git push origin main
echo "Pushed to Railway"
