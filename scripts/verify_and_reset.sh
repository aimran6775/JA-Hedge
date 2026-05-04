#!/usr/bin/env bash
# Wait for Railway redeploy then verify recovery endpoints + execute hard-reset.
set -e
HOST="https://frankensteintrading.com"

echo "==> Waiting 120s for Railway deploy..."
sleep 120

echo "==> Health check"
curl -fsS "$HOST/health" | head -c 400; echo

echo
echo "==> Recovery status BEFORE hard-reset"
curl -fsS "$HOST/api/frankenstein/recovery-status" | python3 -m json.tool || echo "endpoint not yet live, retrying in 30s"
sleep 30
curl -fsS "$HOST/api/frankenstein/recovery-status" | python3 -m json.tool || true

echo
echo "==> Executing HARD RESET (token-gated)"
curl -fsS -X POST "$HOST/api/frankenstein/hard-reset?token=PURGE_FRANKENSTEIN" | python3 -m json.tool

echo
echo "==> Recovery status AFTER hard-reset"
sleep 5
curl -fsS "$HOST/api/frankenstein/recovery-status" | python3 -m json.tool

echo
echo "==> Done. Monitor with:"
echo "  curl -s $HOST/api/frankenstein/recovery-status | jq"
