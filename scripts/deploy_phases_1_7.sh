#!/usr/bin/env bash
# Deploy Phases 1-7: side-balance defense, oversampling, hard-reset,
# tightened recovery params, real circuit breakers, price ceiling, recovery-status endpoint.
set -e
cd "$(dirname "$0")/.."
git add -A
git status --short
git commit -m "feat(phases 1-7): recovery mode - side balance + oversampling + tightened gates + circuit breakers + price ceiling + /recovery-status

Root cause of 0% win rate: 100% YES bias on cheap long-shot contracts (1-9c)
that all settled NO. Model never trained because all labels were one class.

Phase 1: Side-balance gate in scanner blocks trades pushing imbalance >75%
Phase 2: Synthetic oversampling in learner unblocks training
Phase 3: POST /hard-reset endpoint to wipe poisoned memory (token-gated)
Phase 4: Tightened defaults - min_conf 0.32->0.58, min_edge 2.5%->4.5%,
         max_pos 100->10, max_simul 200->30, daily_loss 500->100,
         MAX_DAILY_TRADES 350->100, MAX_PER_EVENT 15->3
Phase 5: Real circuit breakers - kill switch on 8% drawdown, 15 consec
         losses, $100 daily loss; 24h forced cooldown
Phase 6: Price ceiling at 82c + raised floor 10c->18c (avoid long-shot trap)
Phase 7: /recovery-status endpoint with side balance + diagnostics
" || echo "nothing to commit"
git push origin main
echo "pushed - railway should auto-deploy in ~2-3 min"
