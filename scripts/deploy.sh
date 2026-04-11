#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

MSG="${1:-fix: pure REST polling, remove SSE entirely}"

git add -A && git commit -m "$MSG" && git push origin main
