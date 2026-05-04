#!/bin/bash
# Comprehensive endpoint scan — find any 5xx or error
export PATH="/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
BASE="https://frankensteintrading.com"

# Every endpoint the frontend hits
ENDPOINTS=(
  /api/portfolio/balance
  /api/portfolio/positions
  /api/portfolio/fills
  /api/portfolio/pnl
  /api/risk/snapshot
  /api/risk/limits
  /api/frankenstein/status
  /api/frankenstein/health
  /api/frankenstein/analytics
  /api/frankenstein/performance
  /api/frankenstein/performance/snapshot
  /api/frankenstein/performance/categories
  /api/frankenstein/strategy
  /api/frankenstein/learner
  /api/frankenstein/features
  /api/frankenstein/memory
  /api/frankenstein/memory/recent
  /api/frankenstein/memory/pending
  /api/frankenstein/debug/rejections
  /api/frankenstein/chat/welcome
  /api/markets
  /api/dashboard
  /api/sports/games/live
  /api/sports/markets
  /api/intelligence/dashboard
  /api/intelligence/signals
  /api/strategies
  /api/alerts
  /api/agent/status
  /api/strategy/status
)

echo "=== Probing $(echo ${#ENDPOINTS[@]}) endpoints ==="
for ep in "${ENDPOINTS[@]}"; do
  RESULT=$(/usr/bin/curl -s -o /tmp/_body.txt -w "%{http_code}|%{time_total}" -m 20 "${BASE}${ep}")
  STATUS=$(echo "$RESULT" | cut -d'|' -f1)
  TIME=$(echo "$RESULT" | cut -d'|' -f2)
  case "$STATUS" in
    200) MARK="OK " ;;
    307|308|301|302) MARK="REDIR" ;;
    404) MARK="404" ;;
    422|400) MARK="VAL" ;;
    5*) MARK="!!!" ;;
    *) MARK="???" ;;
  esac
  printf "%-5s %3s %6ss  %s\n" "$MARK" "$STATUS" "$TIME" "$ep"
  if [[ "$STATUS" == 5* ]]; then
    echo "    BODY: $(head -c 300 /tmp/_body.txt)"
  fi
done
