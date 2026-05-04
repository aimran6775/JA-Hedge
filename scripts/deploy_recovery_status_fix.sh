#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
git add -A
git commit -m "fix(recovery-status): use _state attribute (frank.state was None)"
git push origin main
echo "==> waiting 100s for redeploy..."
sleep 100
echo "==> recovery-status:"
curl -fsS "https://frankensteintrading.com/api/frankenstein/recovery-status" | python3 -m json.tool
