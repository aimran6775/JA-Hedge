#!/bin/bash
# Deep diagnostic of live Railway deployment
BASE="https://frankensteintrading.com"

echo "=== DASHBOARD SUB-PAGES ==="
for path in / /dashboard /dashboard/frankenstein /dashboard/sports /dashboard/intelligence /dashboard/strategies /dashboard/markets; do
  STATUS=$(/usr/bin/curl -s -L -o /dev/null -w "%{http_code}" -m 15 "${BASE}${path}")
  echo "${STATUS} ${path}"
done

echo ""
echo "=== KEY API PAYLOADS ==="
echo "--- Frank analytics ---"
/usr/bin/curl -s -m 10 "${BASE}/api/frankenstein/analytics" | head -c 600
echo ""
echo ""
echo "--- Recent trades ---"
/usr/bin/curl -s -m 10 "${BASE}/api/frankenstein/memory/recent?n=2" | head -c 600
echo ""
echo ""
echo "--- Risk snapshot ---"
/usr/bin/curl -s -m 10 "${BASE}/api/risk/snapshot" | head -c 400
echo ""
echo ""
echo "--- Dashboard aggregate ---"
/usr/bin/curl -s -m 10 "${BASE}/api/dashboard" | head -c 400
echo ""
echo ""
echo "--- Frank performance ---"
/usr/bin/curl -s -m 10 "${BASE}/api/frankenstein/performance" | head -c 400
echo ""
echo ""
echo "--- Frank strategy ---"
/usr/bin/curl -s -m 10 "${BASE}/api/frankenstein/strategy" | head -c 400
echo ""
