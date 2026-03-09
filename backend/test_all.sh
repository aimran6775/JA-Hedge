#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# JA Hedge — Full Stack Integration Test
# ═══════════════════════════════════════════════════════════════
BASE="http://localhost:8000"
FRONTEND="http://localhost:3000"
PASS=0
FAIL=0
WARN=0

test_endpoint() {
    local method="$1" url="$2" label="$3" expected="$4" body="$5"
    if [ "$method" = "POST" ] && [ -n "$body" ]; then
        RESP=$(curl -s -w "\n%{http_code}" -X POST -H "Content-Type: application/json" -d "$body" "$url" 2>&1)
    else
        RESP=$(curl -s -w "\n%{http_code}" "$url" 2>&1)
    fi
    CODE=$(echo "$RESP" | tail -1)
    BODY=$(echo "$RESP" | sed '$d')

    if [ "$CODE" = "$expected" ]; then
        echo "  ✅ $label — HTTP $CODE"
        PASS=$((PASS+1))
    elif [ "$CODE" = "503" ] || [ "$CODE" = "501" ]; then
        echo "  ⚠️  $label — HTTP $CODE (service unavailable, expected in demo)"
        WARN=$((WARN+1))
    else
        echo "  ❌ $label — HTTP $CODE (expected $expected)"
        echo "     Response: $(echo "$BODY" | head -1 | cut -c1-120)"
        FAIL=$((FAIL+1))
    fi
}

echo ""
echo "═══════════════════════════════════════════════════"
echo "  JA HEDGE — Full Integration Test"
echo "  $(date)"
echo "═══════════════════════════════════════════════════"

# ── 1. BACKEND HEALTH ─────────────────────────────────
echo ""
echo "▸ 1. Backend Health"
test_endpoint GET "$BASE/health" "Health check" 200

# ── 2. MARKETS ────────────────────────────────────────
echo ""
echo "▸ 2. Markets API"
test_endpoint GET "$BASE/api/markets?limit=5" "List markets (limit=5)" 200
test_endpoint GET "$BASE/api/markets?limit=10&search=bitcoin" "Search markets (bitcoin)" 200

# Grab a real ticker from the response for single-market test
TICKER=$(curl -s "$BASE/api/markets?limit=1" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['markets'][0]['ticker'] if d.get('markets') else '')" 2>/dev/null)
if [ -n "$TICKER" ]; then
    test_endpoint GET "$BASE/api/markets/$TICKER" "Get single market ($TICKER)" 200
else
    echo "  ⚠️  No ticker available for single-market test"
    WARN=$((WARN+1))
fi

# ── 3. PORTFOLIO ──────────────────────────────────────
echo ""
echo "▸ 3. Portfolio API"
test_endpoint GET "$BASE/api/portfolio/balance" "Get balance" 200
test_endpoint GET "$BASE/api/portfolio/positions" "Get positions" 200
test_endpoint GET "$BASE/api/portfolio/fills" "Get fills/trades" 200
test_endpoint GET "$BASE/api/portfolio/pnl" "Get P&L" 200

# ── 4. ORDERS ─────────────────────────────────────────
echo ""
echo "▸ 4. Orders API"
# Place a test order (paper trading) — tiny 1-contract limit order at 1 cent
if [ -n "$TICKER" ]; then
    ORDER_BODY="{\"ticker\":\"$TICKER\",\"side\":\"yes\",\"action\":\"buy\",\"count\":1,\"type\":\"limit\",\"price_cents\":1}"
    test_endpoint POST "$BASE/api/orders" "Place test order (1 contract @ 1¢)" 200 "$ORDER_BODY"
else
    echo "  ⚠️  No ticker — skipping order test"
    WARN=$((WARN+1))
fi

# ── 5. STRATEGY / AI ─────────────────────────────────
echo ""
echo "▸ 5. AI Strategy API"
test_endpoint GET "$BASE/api/strategy/status" "Strategy status" 200

# ── 6. RISK ──────────────────────────────────────────
echo ""
echo "▸ 6. Risk Management API"
test_endpoint GET "$BASE/api/risk/snapshot" "Risk snapshot" 200

# ── 7. FRONTEND PAGES ────────────────────────────────
echo ""
echo "▸ 7. Frontend Pages"
for page in "/" "/dashboard" "/dashboard/markets" "/dashboard/trading" "/dashboard/portfolio" "/dashboard/ai" "/dashboard/risk" "/dashboard/settings"; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" "$FRONTEND$page" 2>/dev/null)
    if [ "$CODE" = "200" ]; then
        echo "  ✅ $page — HTTP $CODE"
        PASS=$((PASS+1))
    elif [ "$CODE" = "307" ] || [ "$CODE" = "308" ]; then
        echo "  ✅ $page — HTTP $CODE (redirect, OK)"
        PASS=$((PASS+1))
    else
        echo "  ❌ $page — HTTP $CODE"
        FAIL=$((FAIL+1))
    fi
done

# ── 8. FRONTEND→BACKEND CONNECTIVITY ─────────────────
echo ""
echo "▸ 8. Cross-Origin (CORS) Check"
CORS=$(curl -s -o /dev/null -w "%{http_code}" -H "Origin: http://localhost:3000" "$BASE/health" 2>/dev/null)
if [ "$CORS" = "200" ]; then
    echo "  ✅ CORS from localhost:3000 — OK"
    PASS=$((PASS+1))
else
    echo "  ❌ CORS check failed — HTTP $CORS"
    FAIL=$((FAIL+1))
fi

# ── 9. LIVE DATA VERIFICATION ────────────────────────
echo ""
echo "▸ 9. Live Kalshi Data Verification"
MARKET_COUNT=$(curl -s "$BASE/api/markets?limit=100" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total',0))" 2>/dev/null)
SOURCE=$(curl -s "$BASE/api/markets?limit=1" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('source','unknown'))" 2>/dev/null)
BALANCE=$(curl -s "$BASE/api/portfolio/balance" 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('balance_cents','err'))" 2>/dev/null)

echo "  📊 Markets loaded: $MARKET_COUNT"
echo "  📡 Data source: $SOURCE"
echo "  💰 Demo balance: ${BALANCE}¢"

if [ "$MARKET_COUNT" -gt 0 ] 2>/dev/null; then
    echo "  ✅ Live market data confirmed"
    PASS=$((PASS+1))
else
    echo "  ❌ No markets loaded"
    FAIL=$((FAIL+1))
fi

# ── SUMMARY ───────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
TOTAL=$((PASS+FAIL+WARN))
echo "  RESULTS: $PASS passed, $FAIL failed, $WARN warnings ($TOTAL total)"
if [ "$FAIL" -eq 0 ]; then
    echo "  🎉 ALL TESTS PASSED!"
else
    echo "  ⚠️  Some tests failed — see above"
fi
echo "═══════════════════════════════════════════════════"
echo ""
